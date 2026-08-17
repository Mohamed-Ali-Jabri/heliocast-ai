
"""
STEG HelioCast AI - Pipeline de modélisation v14
================================================
"""

from __future__ import annotations

import argparse # recevoir des paramétres depiuis le trminal 
import hashlib
import json
import logging
import os
import random
import time
import warnings
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tempfile
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pvlib
import yaml


# ============================================================================
# 1. CONFIGURATION
# ============================================================================

RANDOM_SEED = 42

TZ = "Africa/Tunis"

MAPE_THRESHOLD_MW = 0.5

SHORT_GAP_LIMIT_H = 3

# MIN_VALID_MINUTES = 30

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONFIG_FILE = PROJECT_ROOT / "config" / "sites.yaml"

DATA_DIR = PROJECT_ROOT / "data"

MERGE_PATH = (
    DATA_DIR
    / "merged"
    / "GLOBAL"
    / "merged_all_sites.csv"
)

QUALITY_PATH = (
    DATA_DIR
    / "production_cleaned"
    / "cleaned_hourly"
    / "production_hourly_all_sites.csv"
)

FINAL_DIR = DATA_DIR / "final_data"
MODELS_DIR = PROJECT_ROOT / "models_final_14"
REPORTS_DIR = PROJECT_ROOT / "reports"
FIGURES_DIR = PROJECT_ROOT / "figures"
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "modeling_v14.log"

def get_catboost_train_dir() -> Path:

    d = MODELS_DIR / "catboost_train"
    d.mkdir(parents=True, exist_ok=True)
    return d

# 
# LOGGER (console + fichier)
# 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)

if not LOG_FILE.parent.exists():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

_file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)

_file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )
)

logger.addHandler(_file_handler)


# ============================================================================
# 2. VARIABLES METEO
# ============================================================================

WEATHER_COLS = [
    "shortwave_radiation",
    "direct_normal_irradiance",
    "direct_radiation",
    "diffuse_radiation",
    "temperature_2m",
    "wind_speed_10m",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "relative_humidity_2m",
    "visibility",
    "precipitation",
]


# ============================================================================
# 3. COORDONNEES DES SITES
# ============================================================================

SITE_COORDS = {
    "tozeur_1": (33.90859854822346, 8.046303098866254, 154),
    "tozeur_2": (33.90859854822346, 8.046303098866254, 154),
    "feriana_csfb": (34.88905006548165, 8.552969431357354, 696),
    "feriana_csfc": (34.88920040927399, 8.55338789547548, 696),
    "elmourabitine_eni": (33.0502272570142, 10.463332301292539, 177),
    "meknassi_eppm": (34.60536489121733, 9.60224390009452, 257),
}


# ============================================================================
# 4. VALIDATION TEMPORELLE
# ============================================================================

CV_FOLDS = [
    ("2024-01-01", "2024-04-01"),
    ("2024-04-01", "2024-07-01"),
    ("2024-07-01", "2024-10-01"),
    ("2024-10-01", "2025-01-01"),
    ("2025-01-01", "2025-04-01"),
]

HOLDOUT_START = "2025-07-01"

# Seuil de gain CV pour préférer l'ensemble au meilleur modèle seul.
ENSEMBLE_GAIN_THRESHOLD_PCT = 1.0


# ============================================================================
# 5. CHARGEMENT CONFIGURATION SITES
# ============================================================================

def load_sites_config() -> dict:
    """
    Charge config/sites.yaml
    """

    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Fichier sites.yaml introuvable : {CONFIG_FILE}"
        )

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config or "sites" not in config:
        raise ValueError(
            "sites.yaml vide ou clé 'sites' absente."
        )

    sites = {}

    for site in config["sites"]:
        if "id" not in site:
            raise ValueError(
                "Un site dans sites.yaml ne possède pas de clé 'id'."
            )

        sites[site["id"]] = site

    return sites


def build_capacity_map() -> dict[str, float]:
    """
    capacité MW depuis sites.yaml.
    """

    sites = load_sites_config()

    capacities = {}

    for site_id, site in sites.items():

        capacity = (
            site.get("installed_capacity_mwp")
            or site.get("installed_capacity_mw")
        )

        if capacity is None:
            raise ValueError(
                f"Capacité installée absente pour {site_id} "
                f"dans {CONFIG_FILE}"
            )

        capacities[site_id] = float(capacity)

    return capacities


# ============================================================================
# 6. CHARGEMENT DATA
# ============================================================================

def load_raw_data() -> pd.DataFrame:
    
    #Charge merged_all_sites.csv.

    if not MERGE_PATH.exists():
        raise FileNotFoundError(
            f"Dataset merged introuvable : {MERGE_PATH}"
        )

    df = pd.read_csv(
        MERGE_PATH,
        parse_dates=["timestamp"],
    )

    required = [
        "timestamp",
        "site_id",
        "production_mw",
        *WEATHER_COLS,
        "is_day",
    ]

    missing = [
        col for col in required
        if col not in df.columns
    ]

    if missing:
        raise ValueError(
            "Colonnes manquantes dans merged_all_sites.csv : "
            f"{missing}"
        )

    return df


def load_quality_signal() -> pd.DataFrame | None:
    """
    Charge les indicateurs de qualité SCADA.

    Optionnel : si les colonnes n_valid_minutes / production_mw_std
    sont absentes, le signal est ignoré avec un avertissement explicite
    (ne jamais faire échouer le pipeline en silence).
    """

    if not QUALITY_PATH.exists():
        logger.warning(
            "Signal qualité absent : %s",
            QUALITY_PATH,
        )
        return None

    quality = pd.read_csv(
        QUALITY_PATH,
        parse_dates=["timestamp"],
    )

    required = [
        "site_id",
        "timestamp",
        "n_valid_minutes",
        "production_mw_std",
    ]

    missing = [
        col for col in required
        if col not in quality.columns
    ]

    if missing:
        logger.warning(
            "Signal qualité ignoré, colonnes absentes : %s. "
            "is_low_confidence_reading sera toujours False.",
            missing,
        )
        return None

    return quality[required].copy()


# ============================================================================
# 7. CONTROLE TIMESTAMP
# ============================================================================

def validate_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Vérifie les timestamps.
    """

    df = df.copy()

    if df["timestamp"].isna().any():
        raise ValueError(
            "Des timestamps sont manquants."
        )

    if df["timestamp"].dt.tz is not None:
        raise ValueError(
            "Les timestamps du dataset doivent être naïfs "
            "avant l'utilisation de tz_localize(Africa/Tunis)."
        )

    for site_id, group in df.groupby("site_id"):

        timestamps = (
            group["timestamp"]
            .sort_values()
            .drop_duplicates()
        )

        if len(timestamps) < 2:
            continue

        deltas = timestamps.diff().dropna()

        non_hourly = deltas[
            deltas != pd.Timedelta(hours=1)
        ]

        if len(non_hourly) > 0:
            logger.warning(
                "%s : %d intervalle(s) non horaire(s) détecté(s).",
                site_id,
                len(non_hourly),
            )

    return df


# ============================================================================
# 8. REINDEXATION HORAIRE
# ============================================================================

def reindex_and_interpolate(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Crée une grille horaire complète par site.

    - production_mw n'est JAMAIS interpolée ;
    - seules les variables météo sont interpolées (max 3h) ;
    - aucun décalage temporel.
    """

    frames = []

    for site_id, group in df.groupby(
        "site_id",
        sort=False,
    ):

        group = (
            group
            .sort_values("timestamp")
            .drop_duplicates(
                subset=["timestamp"],
                keep="first",
            )
            .set_index("timestamp")
        )

        full_index = pd.date_range(
            start=group.index.min(),
            end=group.index.max(),
            freq="h",
        )

        group = group.reindex(full_index)

        group.index.name = "timestamp"

        group["site_id"] = site_id

        if "timezone" in group.columns:
            group["timezone"] = (
                group["timezone"]
                .ffill()
                .bfill()
            )

        available_weather = [
            col for col in WEATHER_COLS
            if col in group.columns
        ]

        group[available_weather] = (
            group[available_weather]
            .interpolate(
                method="time",
                limit=SHORT_GAP_LIMIT_H,
                limit_area="inside",
            )
        )

        frames.append(
            group.reset_index()
        )

    result = pd.concat(
        frames,
        ignore_index=True,
    )

    return result


# ============================================================================
# 9. FEATURES CALENDRIER
# ============================================================================

def add_calendar_features(
    df: pd.DataFrame,
) -> pd.DataFrame:

    df = df.copy()

    ts = df["timestamp"]

    df["hour"] = ts.dt.hour
    df["day_of_week"] = ts.dt.dayofweek
    df["month"] = ts.dt.month
    df["day_of_year"] = ts.dt.dayofyear

    df["hour_sin"] = np.sin(
        2 * np.pi * df["hour"] / 24
    )

    df["hour_cos"] = np.cos(
        2 * np.pi * df["hour"] / 24
    )

    df["month_sin"] = np.sin(
        2 * np.pi * df["month"] / 12
    )

    df["month_cos"] = np.cos(
        2 * np.pi * df["month"] / 12
    )

    return df


# ============================================================================
# 10. CORRECTIONS PRODUCTION
# ============================================================================

def apply_corrections(
    df: pd.DataFrame,
    quality: pd.DataFrame | None,
    capacity_map: dict[str, float],
) -> pd.DataFrame:

    df = df.copy()

    # ------------------------------------------------------------------
    # is_day
    # ------------------------------------------------------------------

    if df["is_day"].isna().any():

        df["is_day"] = df["is_day"].fillna(
            (
                df["shortwave_radiation"] > 0
            ).astype(float)
        )

    df["is_day"] = df["is_day"].astype("Int64")

    # ------------------------------------------------------------------
    # Bruit nocturne
    # ------------------------------------------------------------------

    night_noise = (
        (df["is_day"] == 0)
        & (df["production_mw"] > 0)
    )

    df["night_noise_clipped"] = night_noise

    df.loc[
        night_noise,
        "production_mw",
    ] = 0.0

    # ------------------------------------------------------------------
    # Arrêt pendant irradiation
    # ------------------------------------------------------------------

    outage = (
        (df["is_day"] == 1)
        & (df["shortwave_radiation"] > 50)
        & (df["production_mw"] == 0)
    )

    df["is_outage_flag"] = outage

    # ------------------------------------------------------------------
    # Capacity factor avec capacité réelle du site
    # ------------------------------------------------------------------

    df["installed_capacity_mw"] = (
        df["site_id"]
        .map(capacity_map)
    )

    if df["installed_capacity_mw"].isna().any():

        unknown_sites = (
            df.loc[
                df["installed_capacity_mw"].isna(),
                "site_id",
            ]
            .unique()
            .tolist()
        )

        raise ValueError(
            "Capacité inconnue pour les sites : "
            f"{unknown_sites}"
        )

    df["capacity_factor"] = (
        df["production_mw"]
        / df["installed_capacity_mw"]
    )

    # ------------------------------------------------------------------
    # Qualité SCADA
    # ------------------------------------------------------------------

    if quality is not None:

        df = df.merge(
            quality,
            on=["site_id", "timestamp"],
            how="left",
            validate="one_to_one",
        )

        # df["is_low_confidence_reading"] = (
        #     df["n_valid_minutes"]
        #     < MIN_VALID_MINUTES
        # )

        df["is_low_confidence_reading"] = (
            df["is_low_confidence_reading"]
            .fillna(False)
        )

    else:

        df["n_valid_minutes"] = np.nan
        df["production_mw_std"] = np.nan
        df["is_low_confidence_reading"] = False

    return df


# ============================================================================
# 11. DATASET MODELING READY
# ============================================================================

def build_modeling_ready_dataset() -> pd.DataFrame:

    raw = load_raw_data()

    raw = validate_timestamps(raw)

    quality = load_quality_signal()

    capacity_map = build_capacity_map()

    clean = reindex_and_interpolate(raw)

    clean = add_calendar_features(clean)

    clean = apply_corrections(
        clean,
        quality,
        capacity_map,
    )

    report = {
        "rows_raw": len(raw),
        "rows_after_reindex": len(clean),
        "rows_added_by_reindex": (
            len(clean) - len(raw)
        ),
        "rows_night_noise_clipped": int(
            clean["night_noise_clipped"].sum()
        ),
        "rows_outage_detected": int(
            clean["is_outage_flag"].sum()
        ),
        "rows_low_confidence": int(
            clean["is_low_confidence_reading"].sum()
        ),
    }

    ready = clean[
        clean["production_mw"].notna()
        & ~clean[WEATHER_COLS]
            .isna()
            .any(axis=1)
        & ~clean["is_outage_flag"]
        & ~clean["is_low_confidence_reading"]
    ].copy()

    ready = ready.reset_index(drop=True)

    report["rows_modeling_ready"] = len(ready)

    FINAL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    clean.to_csv(
        FINAL_DIR / "steg_pv_clean_full.csv",
        index=False,
    )

    ready.to_csv(
        FINAL_DIR / "steg_pv_modeling_ready.csv",
        index=False,
    )

    logger.info("========== PRETRAITEMENT ==========")

    for key, value in report.items():
        logger.info(
            "%-35s : %s",
            key,
            value,
        )

    return ready


# ============================================================================
# 12. GEOMETRIE SOLAIRE PVLIB
# ============================================================================

def add_solar_geometry(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Calcule la position solaire. Le timestamp n'est PAS modifié.
    """

    frames = []

    for site_id, group in df.groupby(
        "site_id",
        sort=False,
    ):

        if site_id not in SITE_COORDS:
            raise ValueError(
                f"Coordonnées inconnues pour {site_id}"
            )

        lat, lon, elevation = SITE_COORDS[
            site_id
        ]

        group = (
            group
            .sort_values("timestamp")
            .copy()
        )

        timestamps = pd.DatetimeIndex(
            group["timestamp"]
        )

        if timestamps.tz is None:

            ts_local = timestamps.tz_localize(
                TZ
            )

        else:

            ts_local = timestamps.tz_convert(
                TZ
            )

        solpos = (
            pvlib.solarposition
            .get_solarposition(
                ts_local,
                lat,
                lon,
                altitude=elevation,
            )
        )

        group["solar_zenith"] = (
            solpos["apparent_zenith"]
            .to_numpy()
        )

        group["solar_elevation"] = (
            solpos["apparent_elevation"]
            .to_numpy()
        )

        group["solar_azimuth"] = (
            solpos["azimuth"]
            .to_numpy()
        )

        dni_extra = (
            pvlib.irradiance
            .get_extra_radiation(
                ts_local
            )
        )

        airmass = (
            pvlib.atmosphere
            .get_relative_airmass(
                solpos["apparent_zenith"]
            )
        )

        try:

            linke = (
                pvlib.clearsky
                .lookup_linke_turbidity(
                    ts_local,
                    lat,
                    lon,
                )
            )

        except Exception:

            linke = pd.Series(
                3.0,
                index=ts_local,
            )

        clearsky = (
            pvlib.clearsky
            .ineichen(
                solpos["apparent_zenith"],
                airmass,
                linke,
                altitude=elevation,
                dni_extra=dni_extra,
            )
        )

        group["clearsky_ghi"] = (
            clearsky["ghi"].to_numpy()
        )

        group["clearsky_dni"] = (
            clearsky["dni"].to_numpy()
        )

        group["clearsky_dhi"] = (
            clearsky["dhi"].to_numpy()
        )

        frames.append(group)

    return pd.concat(
        frames,
        ignore_index=True,
    )


# ============================================================================
# 13. FEATURES PHYSIQUES
# ============================================================================

def add_physical_features(
    df: pd.DataFrame,
) -> pd.DataFrame:

    df = df.copy()

    # ------------------------------------------------------------------
    # Clear-sky index
    # ------------------------------------------------------------------

    clearsky_ghi = (
        df["clearsky_ghi"]
        .clip(lower=1e-3)
    )

    df["clearsky_index"] = (
        df["shortwave_radiation"]
        / clearsky_ghi
    ).clip(0, 1.5)

    df.loc[
        df["solar_elevation"] <= 0,
        "clearsky_index",
    ] = 0.0

    # ------------------------------------------------------------------
    # Température cellule approximative
    # ------------------------------------------------------------------

    df["cell_temp_proxy"] = (
        df["temperature_2m"]
        + (45 - 20)
        / 800
        * df["shortwave_radiation"]
    )

    # ------------------------------------------------------------------
    # Interaction nuages / irradiation
    # ------------------------------------------------------------------

    df["cloud_cover_x_ghi"] = (
        df["cloud_cover"]
        / 100.0
        * df["shortwave_radiation"]
    )

    # ------------------------------------------------------------------
    # Saison
    # ------------------------------------------------------------------

    df["doy_sin"] = np.sin(
        2 * np.pi
        * df["day_of_year"]
        / 365.25
    )

    df["doy_cos"] = np.cos(
        2 * np.pi
        * df["day_of_year"]
        / 365.25
    )

    return df


# ============================================================================
# 14. BUILD FEATURE DATASET
# ============================================================================

def build_feature_dataset(
    df: pd.DataFrame,
) -> pd.DataFrame:

    t0 = time.time()

    out = add_solar_geometry(df)

    out = add_physical_features(out)

    out = (
        out
        .sort_values(
            ["site_id", "timestamp"]
        )
        .reset_index(drop=True)
    )

    FINAL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    out.to_csv(
        FINAL_DIR / "steg_pv_features.csv",
        index=False,
    )

    logger.info(
        "Feature engineering : %s | %.1fs",
        out.shape,
        time.time() - t0,
    )

    return out


# ============================================================================
# 15. FEATURES FINALES
# ============================================================================

FINAL_FEATURE_COLS = [

    # Météo
    "shortwave_radiation",
    "direct_normal_irradiance",
    "diffuse_radiation",
    "temperature_2m",
    "wind_speed_10m",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "relative_humidity_2m",
    "visibility",
    "precipitation",

    # Calendrier
    "hour",
    "day_of_week",
    "hour_sin",
    "hour_cos",
    "doy_sin",
    "doy_cos",

    # Jour/nuit
    "is_day",

    # Soleil
    "solar_elevation",
    "solar_azimuth",
    "clearsky_dni",

    # Physique
    "clearsky_index",
    "cell_temp_proxy",
    "cloud_cover_x_ghi",
]


# ============================================================================
# 16. MATRICE DE DESIGN
# ============================================================================

def build_design_matrix(
    data: pd.DataFrame,
    feature_cols: list[str] | None = None,
) -> pd.DataFrame:

    cols = (
        feature_cols
        if feature_cols is not None
        else FINAL_FEATURE_COLS
    )

    missing = [
        col for col in cols
        if col not in data.columns
    ]

    if missing:
        raise ValueError(
            f"Features manquantes : {missing}"
        )

    X = data[cols].copy()

    site_dummies = pd.get_dummies(
        data["site_id"],
        prefix="site",
        dtype=float,
    )

    X = pd.concat(
        [X, site_dummies],
        axis=1,
    )

    return X


# ============================================================================
# 17. SPLITS CHRONOLOGIQUES
# ============================================================================

def cv_split_indices(data: pd.DataFrame):

    ts = data["timestamp"]

    for train_end, val_end in CV_FOLDS:

        train_idx = np.where(
            ts < train_end
        )[0]

        val_idx = np.where(
            (ts >= train_end)
            & (ts < val_end)
        )[0]

        if len(train_idx) == 0:
            logger.warning(
                "Fold sans train : %s",
                train_end,
            )
            continue

        if len(val_idx) == 0:
            logger.warning(
                "Fold sans validation : %s",
                train_end,
            )
            continue

        yield train_idx, val_idx
  

def final_split_indices(
    data: pd.DataFrame,
):

    ts = data["timestamp"]

    train_idx = np.where(
        ts < HOLDOUT_START
    )[0]

    test_idx = np.where(
        ts >= HOLDOUT_START
    )[0]

    return train_idx, test_idx


# ============================================================================
# 18. METRIQUES
# ============================================================================

def compute_metrics(
    y_true,
    y_pred,
    capacity: float | None = None,
    mape_threshold_mw: float = MAPE_THRESHOLD_MW,
) -> dict:

    y_true = np.asarray(
        y_true,
        dtype=float,
    )

    y_pred = np.asarray(
        y_pred,
        dtype=float,
    )

    err = y_pred - y_true

    mae = np.mean(
        np.abs(err)
    )

    rmse = np.sqrt(
        np.mean(err ** 2)
    )

    ss_res = np.sum(
        err ** 2
    )

    ss_tot = np.sum(
        (y_true - y_true.mean()) ** 2
    )

    r2 = (
        1 - ss_res / ss_tot
        if ss_tot > 0
        else np.nan
    )

    mask = (
        y_true > mape_threshold_mw
    )

    if mask.sum() > 0:

        mape = (
            np.mean(
                np.abs(
                    err[mask]
                    / y_true[mask]
                )
            )
            * 100
        )

    else:
        mape = np.nan

    result = {
        "MAE": mae,
        "RMSE": rmse,
        "R2": r2,
        "MAPE_daytime_%": mape,
        "n_samples": len(y_true),
    }

    if capacity is not None:

        result["nMAE_%"] = (
            mae / capacity * 100
        )

        result["nRMSE_%"] = (
            rmse / capacity * 100
        )

    return result


def compute_global_metrics(
    df: pd.DataFrame,
    y_true,
    y_pred,
    capacity_map: dict[str, float],
) -> dict:
    """
    Métriques globales normalisées par la capacité moyenne pondérée
    des lignes évaluées.
    """

    capacities = (
        df["site_id"]
        .map(capacity_map)
        .to_numpy(
            dtype=float
        )
    )

    mean_capacity = float(
        np.nanmean(capacities)
    )

    return compute_metrics(
        y_true,
        y_pred,
        capacity=mean_capacity,
    )


def compute_global_metrics_by_site(
    df: pd.DataFrame,
    y_true,
    y_pred,
) -> pd.DataFrame:

    tmp = df[
        ["site_id"]
    ].copy()

    tmp["y_true"] = y_true
    tmp["y_pred"] = y_pred

    capacity_map = build_capacity_map()

    rows = []

    for site_id, group in tmp.groupby(
        "site_id"
    ):

        metrics = compute_metrics(
            group["y_true"],
            group["y_pred"],
            capacity=capacity_map[site_id],
        )

        metrics["site_id"] = site_id

        rows.append(metrics)

    return (
        pd.DataFrame(rows)
        .set_index("site_id")
        .sort_index()
    )


# ============================================================================
# 19. MODELES
# ============================================================================

def _fit_with_early_stop(
    model,
    X_train,
    y_train,
    X_val,
    y_val,
):

    name = model.__class__.__name__

    if name == "XGBRegressor":

        model.fit(
            X_train,
            y_train,
            eval_set=[
                (X_val, y_val)
            ],
            verbose=False,
        )

    elif name == "LGBMRegressor":

        import lightgbm as lgb

        model.fit(
            X_train,
            y_train,
            eval_set=[
                (X_val, y_val)
            ],
            callbacks=[
                lgb.early_stopping(
                    30,
                    verbose=False,
                ),
                lgb.log_evaluation(0),
            ],
        )

    elif name == "CatBoostRegressor":

        model.fit(
            X_train,
            y_train,
            eval_set=(
                X_val,
                y_val,
            ),
            verbose=False,
        )

    else:

        model.fit(
            X_train,
            y_train,
        )

    return model


def _rmse_cv(
    model_factory,
    X,
    y,
    folds,
    return_list=False,
):

    scores = []

    for train_idx, val_idx in folds:

        model = model_factory()

        model = _fit_with_early_stop(
            model,
            X.iloc[train_idx],
            y[train_idx],
            X.iloc[val_idx],
            y[val_idx],
        )

        pred = model.predict(
            X.iloc[val_idx]
        )

        rmse = np.sqrt(
            np.mean(
                (
                    pred
                    - y[val_idx]
                ) ** 2
            )
        )

        scores.append(rmse)

    if return_list:
        return scores

    return float(
        np.mean(scores)
    )


# ============================================================================
# 20. OBJECTIVES OPTUNA
# ============================================================================

def _objective_xgboost(
    trial,
    X,
    y,
    folds,
):

    import xgboost as xgb

    params = dict(

        n_estimators=1000,

        max_depth=trial.suggest_int(
            "max_depth",
            3,
            10,
        ),

        learning_rate=trial.suggest_float(
            "learning_rate",
            0.01,
            0.3,
            log=True,
        ),

        subsample=trial.suggest_float(
            "subsample",
            0.6,
            1.0,
        ),

        colsample_bytree=trial.suggest_float(
            "colsample_bytree",
            0.6,
            1.0,
        ),

        min_child_weight=trial.suggest_int(
            "min_child_weight",
            1,
            20,
        ),

        reg_alpha=trial.suggest_float(
            "reg_alpha",
            1e-3,
            10.0,
            log=True,
        ),

        reg_lambda=trial.suggest_float(
            "reg_lambda",
            1e-3,
            10.0,
            log=True,
        ),

        gamma=trial.suggest_float(
            "gamma",
            1e-3,
            5.0,
            log=True,
        ),

        n_jobs=1,
        tree_method="hist",
        early_stopping_rounds=30,
        random_state=RANDOM_SEED,
    )

    return _rmse_cv(
        lambda: xgb.XGBRegressor(**params),
        X,
        y,
        folds,
    )


def _objective_lightgbm(
    trial,
    X,
    y,
    folds,
):

    import lightgbm as lgb

    params = dict(

        n_estimators=1000,

        max_depth=trial.suggest_int(
            "max_depth",
            3,
            10,
        ),

        num_leaves=trial.suggest_int(
            "num_leaves",
            15,
            200,
        ),

        learning_rate=trial.suggest_float(
            "learning_rate",
            0.01,
            0.3,
            log=True,
        ),

        subsample=trial.suggest_float(
            "subsample",
            0.6,
            1.0,
        ),

        colsample_bytree=trial.suggest_float(
            "colsample_bytree",
            0.6,
            1.0,
        ),

        min_child_samples=trial.suggest_int(
            "min_child_samples",
            5,
            100,
        ),

        reg_alpha=trial.suggest_float(
            "reg_alpha",
            1e-3,
            10.0,
            log=True,
        ),

        reg_lambda=trial.suggest_float(
            "reg_lambda",
            1e-3,
            10.0,
            log=True,
        ),

        n_jobs=1,
        verbosity=-1,
        random_state=RANDOM_SEED,
    )

    return _rmse_cv(
        lambda: lgb.LGBMRegressor(**params),
        X,
        y,
        folds,
    )


def _objective_catboost(
    trial,
    X,
    y,
    folds,
):

    import catboost as cb

    params = dict(

        iterations=1000,

        depth=trial.suggest_int(
            "depth",
            3,
            10,
        ),

        learning_rate=trial.suggest_float(
            "learning_rate",
            0.01,
            0.3,
            log=True,
        ),

        l2_leaf_reg=trial.suggest_float(
            "l2_leaf_reg",
            1e-2,
            20.0,
            log=True,
        ),

        subsample=trial.suggest_float(
            "subsample",
            0.6,
            1.0,
        ),

        bootstrap_type="Bernoulli",
        thread_count=1,
        verbose=False,
        early_stopping_rounds=30,
        random_seed=RANDOM_SEED,
        allow_writing_files=False,
    )

    return _rmse_cv(
        lambda: cb.CatBoostRegressor(**params),
        X,
        y,
        folds,
    )


def _objective_histgb(
    trial,
    X,
    y,
    folds,
):

    from sklearn.ensemble import (
        HistGradientBoostingRegressor,
    )

    params = dict(

        max_iter=trial.suggest_int(
            "max_iter",
            100,
            600,
        ),

        max_depth=trial.suggest_int(
            "max_depth",
            3,
            12,
        ),

        learning_rate=trial.suggest_float(
            "learning_rate",
            0.01,
            0.3,
            log=True,
        ),

        min_samples_leaf=trial.suggest_int(
            "min_samples_leaf",
            5,
            100,
        ),

        l2_regularization=trial.suggest_float(
            "l2_regularization",
            1e-3,
            10.0,
            log=True,
        ),

        max_leaf_nodes=trial.suggest_int(
            "max_leaf_nodes",
            15,
            200,
        ),

        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=20,
        random_state=RANDOM_SEED,
    )

    return _rmse_cv(
        lambda: HistGradientBoostingRegressor(**params),
        X,
        y,
        folds,
    )


def _objective_extratrees(
    trial,
    X,
    y,
    folds,
):

    from sklearn.ensemble import ExtraTreesRegressor

    params = dict(

        n_estimators=trial.suggest_int(
            "n_estimators",
            100,
            300,
        ),

        max_depth=trial.suggest_int(
            "max_depth",
            6,
            16,
        ),

        min_samples_leaf=trial.suggest_int(
            "min_samples_leaf",
            2,
            30,
        ),

        max_features=trial.suggest_float(
            "max_features",
            0.4,
            1.0,
        ),

        n_jobs=1,
        random_state=RANDOM_SEED,
    )

    return _rmse_cv(
        lambda: ExtraTreesRegressor(**params),
        X,
        y,
        folds,
    )


def _objective_randomforest(
    trial,
    X,
    y,
    folds,
):

    from sklearn.ensemble import RandomForestRegressor

    params = dict(

        n_estimators=trial.suggest_int(
            "n_estimators",
            60,
            150,
        ),

        max_depth=trial.suggest_int(
            "max_depth",
            5,
            10,
        ),

        min_samples_leaf=trial.suggest_int(
            "min_samples_leaf",
            5,
            40,
        ),

        max_features=trial.suggest_float(
            "max_features",
            0.4,
            1.0,
        ),

        max_samples=trial.suggest_float(
            "max_samples",
            0.3,
            0.7,
        ),

        n_jobs=1,
        random_state=RANDOM_SEED,
    )

    return _rmse_cv(
        lambda: RandomForestRegressor(**params),
        X,
        y,
        folds,
    )


def _objective_mlp(
    trial,
    X,
    y,
    folds,
):

    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler

    arch_options = [
        (64,),
        (128,),
        (64, 32),
        (128, 64),
        (128, 64, 32),
    ]

    arch_idx = trial.suggest_int(
        "arch_idx",
        0,
        len(arch_options) - 1,
    )

    alpha = trial.suggest_float(
        "alpha",
        1e-5,
        1e-1,
        log=True,
    )

    lr_init = trial.suggest_float(
        "learning_rate_init",
        1e-4,
        1e-2,
        log=True,
    )

    scores = []

    for train_idx, val_idx in folds:

        X_train = X.iloc[train_idx]
        X_val = X.iloc[val_idx]

        scaler = StandardScaler().fit(
            X_train
        )

        model = MLPRegressor(
            hidden_layer_sizes=arch_options[
                arch_idx
            ],
            alpha=alpha,
            learning_rate_init=lr_init,
            early_stopping=True,
            n_iter_no_change=15,
            max_iter=300,
            validation_fraction=0.15,
            random_state=RANDOM_SEED,
        )

        model.fit(
            scaler.transform(X_train),
            y[train_idx],
        )

        pred = model.predict(
            scaler.transform(X_val)
        )

        rmse = np.sqrt(
            np.mean(
                (
                    pred
                    - y[val_idx]
                ) ** 2
            )
        )

        scores.append(rmse)

    return float(
        np.mean(scores)
    )


# ============================================================================
# 21. MODELES / BUDGET
# ============================================================================

MODEL_SPECS = {

    "xgboost": (
        _objective_xgboost,
        20,
        240,
    ),

    "lightgbm": (
        _objective_lightgbm,
        20,
        180,
    ),

    "histgb": (
        _objective_histgb,
        20,
        180,
    ),

    "catboost": (
        _objective_catboost,
        12,
        180,
    ),

    "extratrees": (
        _objective_extratrees,
        12,
        180,
    ),

    "randomforest": (
        _objective_randomforest,
        8,
        240,
    ),

    "mlp": (
        _objective_mlp,
        12,
        150,
    ),
}


# ============================================================================
# 22. HPO (avec invalidation du cache par hash des données)
# ============================================================================

def compute_data_hash(
    X: pd.DataFrame,
    y: np.ndarray,
) -> str:
    """
    Empreinte md5 de (X, y) pour invalider les caches Optuna quand
    les données d'entraînement changent.

    Hash colonne par colonne en float64 : X.to_numpy() peut renvoyer
    un tableau object (colonnes Int64/nullables mélangées), dont la
    sérialisation n'est PAS stable d'un process à l'autre.
    """

    hash_md5 = hashlib.md5()

    for col in X.columns:

        hash_md5.update(
            np.ascontiguousarray(
                X[col].to_numpy(
                    dtype=float
                )
            ).tobytes()
        )

    hash_md5.update(
        np.ascontiguousarray(
            np.asarray(y, dtype=float)
        ).tobytes()
    )

    return hash_md5.hexdigest()


def run_or_load_hpo(
    name,
    objective,
    n_trials,
    timeout,
    X,
    y,
    folds,
    data_hash,
):
    """
    Exécute ou recharge une optimisation Optuna de façon robuste.

    Règles importantes :
    - le cache JSON est valide uniquement si son data_hash correspond ;
    - si les données changent, l'ancienne base SQLite Optuna est supprimée
      afin de ne jamais réutiliser des trials optimisés sur d'anciennes données ;
    - les trials FAILED/RUNNING ne sont pas comptés comme trials valides ;
    - une étude sans aucun trial COMPLETE valide est recréée ;
    - si Optuna/SQLite rencontre une base incohérente, la base est supprimée
      puis l'étude est recréée proprement.
    """

    import optuna

    MODELS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    cache_path = (
        MODELS_DIR
        / f"hpo_{name}.json"
    )

    db_path = (
        MODELS_DIR
        / f"optuna_{name}.db"
    )

    # ------------------------------------------------------------------
    # 1. Cache JSON
    # ------------------------------------------------------------------

    cached = None

    if cache_path.exists():
        try:
            with open(
                cache_path,
                "r",
                encoding="utf-8",
            ) as f:
                cached = json.load(f)
        except Exception as exc:
            logger.warning(
                "Cache HPO illisible pour %s : %s - suppression.",
                name,
                exc,
            )
            try:
                cache_path.unlink()
            except OSError:
                pass
            cached = None

    if (
        cached is not None
        and cached.get("data_hash") == data_hash
        and isinstance(cached.get("best_params"), dict)
        and cached.get("best_cv_rmse") is not None
    ):
        logger.info(
            "Cache HPO valide : %s (%d essais)",
            name,
            cached.get("n_trials", 0),
        )
        return cached

    # ------------------------------------------------------------------
    # 2. IMPORTANT : si le hash des données change, on ne réutilise PAS
    #    l'ancienne base SQLite Optuna.
    # ------------------------------------------------------------------

    if cached is not None:
        logger.warning(
            "Cache HPO obsolète pour %s "
            "(les données ont changé) - nouvelle étude Optuna.",
            name,
        )

    if db_path.exists():
        try:
            db_path.unlink()
            logger.info(
                "Ancienne base Optuna supprimée pour %s : %s",
                name,
                db_path,
            )
        except OSError as exc:
            logger.warning(
                "Impossible de supprimer %s : %s",
                db_path,
                exc,
            )

    # ------------------------------------------------------------------
    # 3. Création d'une étude propre
    # ------------------------------------------------------------------

    def create_fresh_study():
        return optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.TPESampler(
                seed=RANDOM_SEED
            ),
            storage=f"sqlite:///{db_path}",
            study_name=name,
            load_if_exists=False,
        )

    try:
        study = create_fresh_study()

    except Exception as exc:
        logger.warning(
            "Création de l'étude Optuna %s impossible : %s",
            name,
            exc,
        )

        # Dernier filet de sécurité pour une DB SQLite incohérente.
        try:
            if db_path.exists():
                db_path.unlink()
        except OSError:
            pass

        study = create_fresh_study()

    # ------------------------------------------------------------------
    # 4. Optimisation
    # ------------------------------------------------------------------

    t0 = time.time()

    study.optimize(
        lambda trial: objective(
            trial,
            X,
            y,
            folds,
        ),
        n_trials=max(1, int(n_trials)),
        timeout=timeout,
    )

    # ------------------------------------------------------------------
    # 5. Ne compter que les trials COMPLETE avec une valeur
    # ------------------------------------------------------------------

    complete_trials = [
        trial
        for trial in study.trials
        if (
            trial.state == optuna.trial.TrialState.COMPLETE
            and trial.value is not None
            and np.isfinite(float(trial.value))
        )
    ]

    if not complete_trials:
        failed_count = sum(
            trial.state == optuna.trial.TrialState.FAIL
            for trial in study.trials
        )

        pruned_count = sum(
            trial.state == optuna.trial.TrialState.PRUNED
            for trial in study.trials
        )

        raise RuntimeError(
            f"Optuna {name} n'a produit aucun trial COMPLETE valide. "
            f"Trials total={len(study.trials)}, "
            f"FAILED={failed_count}, "
            f"PRUNED={pruned_count}. "
            "Vérifier l'erreur du modèle/objective ci-dessus."
        )

    # ------------------------------------------------------------------
    # 6. Sélection explicite du meilleur trial
    # ------------------------------------------------------------------

    best_trial = min(
        complete_trials,
        key=lambda trial: float(trial.value),
    )

    result = {
        "model": name,
        "best_params": dict(best_trial.params),
        "best_cv_rmse": float(best_trial.value),
        "n_trials": len(complete_trials),
        "n_trials_total": len(study.trials),
        "elapsed_sec": (
            time.time() - t0
        ),
        "data_hash": data_hash,
    }

    # ------------------------------------------------------------------
    # 7. Sauvegarde atomique du cache JSON
    # ------------------------------------------------------------------

    tmp_cache_path = cache_path.with_suffix(".tmp")

    with open(
        tmp_cache_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            result,
            f,
            indent=2,
        )

    tmp_cache_path.replace(cache_path)

    logger.info(
        "%s | CV RMSE %.4f | %d trials COMPLETE",
        name,
        result["best_cv_rmse"],
        result["n_trials"],
    )

    return result

def run_hpo(
    X,
    y,
    folds,
    quick=False,
):

    import optuna

    optuna.logging.set_verbosity(
        optuna.logging.WARNING
    )

    data_hash = compute_data_hash(
        X,
        y
    )

    results = {}

    for name, (
        objective,
        n_trials,
        timeout,
    ) in MODEL_SPECS.items():

        if quick:

            n_trials = min(
                n_trials,
                2,
            )

            timeout = min(
                timeout,
                60,
            )

        logger.info(
            "Optimisation %s...",
            name,
        )

        results[name] = run_or_load_hpo(
            name,
            objective,
            n_trials,
            timeout,
            X,
            y,
            folds,
            data_hash,
        )

        logger.info(
            "%s | CV RMSE %.4f | %d essais",
            name,
            results[name]["best_cv_rmse"],
            results[name]["n_trials"],
        )

    return results


def evaluate_best_params_on_folds(
    X,
    y,
    folds,
    hpo_results,
):
    """
    Rejoue les meilleurs hyperparamètres de chaque modèle sur chaque
    fold et sauvegarde la table fold_metrics.csv (métrique par fold).
    """

    rows = []

    for name, res in hpo_results.items():

        scores = _rmse_cv(
            lambda: build_model(
                name,
                res["best_params"],
            ),
            X,
            y,
            folds,
            return_list=True,
        )

        for fold_idx, score in enumerate(
            scores
        ):

            rows.append(
                {
                    "modele": name,
                    "fold": fold_idx + 1,
                    "rmse": score,
                }
            )

    fold_df = (
        pd.DataFrame(rows)
    )

    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    fold_df.to_csv(
        REPORTS_DIR
        / "v14_fold_metrics.csv",
        index=False,
    )

    pivot = (
        fold_df
        .pivot_table(
            index="modele",
            columns="fold",
            values="rmse",
        )
    )

    pivot["mean"] = pivot.mean(axis=1)

    logger.info(
        "\n========== RMSE PAR FOLD (meilleurs params) ==========\n%s",
        pivot.round(4).to_string(),
    )


# ============================================================================
# 23. CONSTRUCTION MODELE
# ============================================================================

def build_model(
    name: str,
    best_params: dict,
):

    import xgboost as xgb
    import lightgbm as lgb
    import catboost as cb

    from sklearn.ensemble import (
        RandomForestRegressor,
        ExtraTreesRegressor,
        HistGradientBoostingRegressor,
    )

    params = dict(best_params)

    if name == "xgboost":

        params.update(
            n_estimators=1000,
            n_jobs=1,
            tree_method="hist",
            random_state=RANDOM_SEED,
        )

        return xgb.XGBRegressor(
            **params
        )

    if name == "lightgbm":

        params.update(
            n_estimators=1000,
            n_jobs=1,
            verbosity=-1,
            random_state=RANDOM_SEED,
        )

        return lgb.LGBMRegressor(
            **params
        )

    if name == "catboost":

        params.update(
            iterations=1000,
            thread_count=1,
            verbose=False,
            bootstrap_type="Bernoulli",
            random_seed=RANDOM_SEED,
            allow_writing_files=False,
        )

        return cb.CatBoostRegressor(
            **params
        )

    if name == "histgb":

        params.update(
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=20,
            random_state=RANDOM_SEED,
        )

        return HistGradientBoostingRegressor(
            **params
        )

    if name == "extratrees":

        params.update(
            n_jobs=1,
            random_state=RANDOM_SEED,
        )

        return ExtraTreesRegressor(
            **params
        )

    if name == "randomforest":

        params.update(
            n_jobs=1,
            random_state=RANDOM_SEED,
        )

        return RandomForestRegressor(
            **params
        )

    if name == "mlp":

        from sklearn.neural_network import (
            MLPRegressor,
        )

        from sklearn.pipeline import (
            Pipeline,
        )

        from sklearn.preprocessing import (
            StandardScaler,
        )

        arch_options = [
            (64,),
            (128,),
            (64, 32),
            (128, 64),
            (128, 64, 32),
        ]

        arch_idx = params.pop(
            "arch_idx"
        )

        params.update(
            hidden_layer_sizes=
                arch_options[arch_idx],
            early_stopping=True,
            n_iter_no_change=15,
            max_iter=300,
            validation_fraction=0.15,
            random_state=RANDOM_SEED,
        )

        return Pipeline(
            [
                (
                    "scaler",
                    StandardScaler(),
                ),
                (
                    "mlp",
                    MLPRegressor(
                        **params
                    ),
                ),
            ]
        )

    raise ValueError(
        f"Modèle inconnu : {name}"
    )


# ============================================================================
# 24. COMPARAISON HOLDOUT (RAPPORT UNIQUEMENT)
# ============================================================================

def compare_models_on_holdout(
    df,
    X,
    y,
    hpo_results,
):

    from sklearn.neural_network import (
        MLPRegressor,
    )

    from sklearn.preprocessing import (
        StandardScaler,
    )

    train_idx, test_idx = (
        final_split_indices(df)
    )

    X_train = X.iloc[train_idx]
    y_train = y[train_idx]

    X_test = X.iloc[test_idx]
    y_test = y[test_idx]

    train_timestamps = df.loc[
        train_idx,
        "timestamp",
    ]

    val_cut = train_timestamps.quantile(
        0.90
    )

    es_train_idx = train_idx[
        df.loc[
            train_idx,
            "timestamp",
        ] < val_cut
    ]

    es_val_idx = train_idx[
        df.loc[
            train_idx,
            "timestamp",
        ] >= val_cut
    ]

    fitted = {}
    rows = []

    arch_options = [
        (64,),
        (128,),
        (64, 32),
        (128, 64),
        (128, 64, 32),
    ]

    # --------------------------------------------------------------
    # Modèles arbres
    # --------------------------------------------------------------

    for name, res in hpo_results.items():

        if name == "mlp":
            continue

        t0 = time.time()

        model = build_model(
            name,
            res["best_params"],
        )

        if name in (
            "xgboost",
            "lightgbm",
            "catboost",
        ):

            model = _fit_with_early_stop(
                model,
                X.iloc[es_train_idx],
                y[es_train_idx],
                X.iloc[es_val_idx],
                y[es_val_idx],
            )

        else:

            model.fit(
                X_train,
                y_train,
            )

        train_time = (
            time.time() - t0
        )

        t0 = time.time()

        pred_test = model.predict(
            X_test
        )

        infer_time = (
            time.time() - t0
        )

        capacity_map = build_capacity_map()

        metrics = compute_global_metrics(
            df.iloc[test_idx],
            y_test,
            pred_test,
            capacity_map,
        )

        metrics.update(
            {
                "modele": name,
                "train_time_s": train_time,
                "infer_rows_per_s": (
                    len(X_test)
                    / max(
                        infer_time,
                        1e-9,
                    )
                ),
            }
        )

        rows.append(metrics)

        fitted[name] = model

        logger.info(
            "%-14s RMSE=%.4f R2=%.4f",
            name,
            metrics["RMSE"],
            metrics["R2"],
        )

    # --------------------------------------------------------------
    # MLP
    # --------------------------------------------------------------

    if "mlp" in hpo_results:

        mlp_params = (
            hpo_results["mlp"]
            ["best_params"]
        )

        scaler = (
            StandardScaler()
            .fit(X_train)
        )

        mlp = MLPRegressor(
            hidden_layer_sizes=
                arch_options[
                    mlp_params["arch_idx"]
                ],

            alpha=mlp_params[
                "alpha"
            ],

            learning_rate_init=
                mlp_params[
                    "learning_rate_init"
                ],

            early_stopping=True,
            n_iter_no_change=15,
            max_iter=300,
            validation_fraction=0.15,
            random_state=RANDOM_SEED,
        )

        t0 = time.time()

        mlp.fit(
            scaler.transform(X_train),
            y_train,
        )

        train_time = (
            time.time() - t0
        )

        t0 = time.time()

        pred_test_mlp = mlp.predict(
            scaler.transform(X_test)
        )

        infer_time = (
            time.time() - t0
        )

        capacity_map = build_capacity_map()

        metrics = compute_global_metrics(
            df.iloc[test_idx],
            y_test,
            pred_test_mlp,
            capacity_map,
        )

        metrics.update(
            {
                "modele": "mlp",
                "train_time_s": train_time,
                "infer_rows_per_s": (
                    len(X_test)
                    / max(
                        infer_time,
                        1e-9,
                    )
                ),
            }
        )

        rows.append(metrics)

        fitted["mlp"] = (
            mlp,
            scaler,
        )

        logger.info(
            "%-14s RMSE=%.4f R2=%.4f",
            "mlp",
            metrics["RMSE"],
            metrics["R2"],
        )

    comparison = (
        pd.DataFrame(rows)
        .set_index("modele")
        .sort_values("RMSE")
    )

    logger.info(
        "\n========== HOLDOUT (rapport uniquement) ==========\n%s",
        comparison[
            [
                "RMSE",
                "R2",
                "MAPE_daytime_%",
                "nMAE_%",
                "nRMSE_%",
            ]
        ]
        .round(4)
        .to_string(),
    )

    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    comparison.to_csv(
        REPORTS_DIR
        / "v14_holdout_comparison.csv",
    )

    preds = {}

    for name, model in fitted.items():

        if name == "mlp":

            mlp_model, scaler = model

            preds[name] = (
                mlp_model.predict(
                    scaler.transform(
                        X_test
                    )
                )
            )

        else:

            preds[name] = (
                model.predict(
                    X_test
                )
            )

    return (
        fitted,
        comparison,
        preds,
        (
            X_test,
            y_test,
        ),
    )


# ============================================================================
# 25. SELECTION FINALE SUR CV (holdout non utilisé pour décider)
# ============================================================================

def select_final_model(
    hpo_results,
    preds,
    y_test,
    df,
):
    """
    Décide le modèle final UNIQUEMENT à partir des RMSE de CV
    walk-forward (hpo_results). Le holdout sert au rapport.

    - top 3 modèles par CV ;
    - poids 1/cv_rmse normalisés ;
    - ensemble si son RMSE CV pondéré gagne > ENSEMBLE_GAIN_THRESHOLD_PCT
      par rapport au meilleur modèle seul, sinon meilleur modèle seul.
    """

    valid_hpo = {
        name: result
        for name, result in hpo_results.items()
        if (
            result.get("best_cv_rmse") is not None
            and np.isfinite(float(result["best_cv_rmse"]))
            and isinstance(result.get("best_params"), dict)
        )
    }

    if not valid_hpo:
        raise RuntimeError(
            "Aucun résultat HPO valide pour sélectionner le modèle final."
        )

    ranked = sorted(
        valid_hpo.items(),
        key=lambda item: (
            float(item[1]["best_cv_rmse"]),
            item[0],
        ),
    )

    top_n = min(
        3,
        len(ranked),
    )

    top_models = [
        name
        for name, _ in ranked[:top_n]
    ]

    weights = {}

    for name in top_models:

        cv_rmse = (
            hpo_results[name]
            ["best_cv_rmse"]
        )

        weights[name] = (
            1.0
            / max(
                cv_rmse,
                1e-9,
            )
        )

    total = sum(
        weights.values()
    )

    weights = {
        key: value / total
        for key, value
        in weights.items()
    }

    best_single = ranked[0][0]

    best_cv_rmse = (
        hpo_results[best_single]
        ["best_cv_rmse"]
    )

    ensemble_cv_rmse = sum(
        weights[name]
        * hpo_results[name]["best_cv_rmse"]
        for name in top_models
    )

    gain_pct = (
        (
            best_cv_rmse
            - ensemble_cv_rmse
        )
        / best_cv_rmse
        * 100
    )

    if gain_pct > ENSEMBLE_GAIN_THRESHOLD_PCT:

        decision = (
            "ensemble("
            + "+".join(top_models)
            + ")"
        )

    else:

        decision = best_single

    # Métriques holdout de la décision (rapport uniquement).
    capacity_map = build_capacity_map()

    if decision.startswith(
        "ensemble"
    ):

        ensemble_pred = sum(
            weights[name]
            * preds[name]
            for name in top_models
        )

        ensemble_metrics = compute_global_metrics(
            df,
            y_test,
            ensemble_pred,
            capacity_map,
        )

        decision_metrics = ensemble_metrics

    else:

        decision_metrics = compute_global_metrics(
            df,
            y_test,
            preds[decision],
            capacity_map,
        )

    logger.info(
        "Ensemble CV pondéré : %s",
        {
            name: round(weight, 3)
            for name, weight
            in weights.items()
        },
    )

    logger.info(
        "Meilleur modèle (CV) : %s | CV RMSE %.4f",
        best_single,
        best_cv_rmse,
    )

    logger.info(
        "Ensemble CV RMSE : %.4f | Gain %.2f%%",
        ensemble_cv_rmse,
        gain_pct,
    )

    logger.info(
        "Décision finale : %s",
        decision,
    )

    return (
        weights,
        top_models,
        gain_pct,
        decision,
        decision_metrics,
    )


# ============================================================================
# 26. SHAP
# ============================================================================

def explain_model(
    fitted,
    best_name,
    X_test,
    sample=3000,
):

    import shap

    model = fitted[
        best_name
    ]

    if isinstance(
        model,
        tuple,
    ):

        logger.info(
            "SHAP ignoré pour MLP."
        )

        return

    shap_sample = (
        X_test
        .sample(
            min(
                sample,
                len(X_test),
            ),
            random_state=RANDOM_SEED,
        )
    )

    try:

        explainer = (
            shap.TreeExplainer(
                model
            )
        )

        shap_values = (
            explainer
            .shap_values(
                shap_sample
            )
        )

    except Exception as exc:

        logger.warning(
            "SHAP indisponible pour %s : %s",
            best_name,
            exc,
        )

        return

    mean_abs_shap = (
        pd.Series(
            np.abs(
                shap_values
            ).mean(axis=0),
            index=shap_sample.columns,
        )
        .sort_values(
            ascending=False
        )
    )

    logger.info(
        "\nTop features SHAP :\n%s",
        mean_abs_shap
        .head(10)
        .round(4)
        .to_string(),
    )

    FIGURES_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    fig, ax = plt.subplots(
        figsize=(8, 7)
    )

    mean_abs_shap.head(15).plot.barh(
        ax=ax
    )

    ax.invert_yaxis()

    ax.set_xlabel(
        "|SHAP| moyen"
    )

    ax.set_title(
        f"Importance SHAP - {best_name}"
    )

    fig.tight_layout()

    fig.savefig(
        FIGURES_DIR
        / "03_shap_importance.png",
        dpi=110,
        bbox_inches="tight",
    )

    plt.close(fig)


# ============================================================================
# 27. ANALYSE ERREURS (métriques sauvegardées en CSV)
# ============================================================================

def _predict_refit(
    best_name,
    fitted,
    X,
):

    if best_name == "mlp":

        model, scaler = (
            fitted["mlp"]
        )

        return model.predict(
            scaler.transform(X)
        )

    return fitted[
        best_name
    ].predict(X)


def analyze_errors(
    df,
    best_name,
    fitted,
    preds,
    X_test,
    y_test,
    comparison,
    X,
    y,
    hpo_results,
):

    _, test_idx = (
        final_split_indices(df)
    )

    pred_best = preds[
        best_name
    ]

    test_meta = df.loc[
        test_idx,
        [
            "timestamp",
            "site_id",
            "hour",
            "month",
            "is_day",
            "clearsky_index",
        ],
    ].copy()

    test_meta["y_true"] = y_test
    test_meta["y_pred"] = pred_best
    test_meta["residual"] = (
        pred_best - y_test
    )

    capacity_map = build_capacity_map()

    # --------------------------------------------------------------
    # Par site
    # --------------------------------------------------------------

    by_site = (
        compute_global_metrics_by_site(
            test_meta,
            y_test,
            pred_best,
        )
    )

    logger.info(
        "\n========== ERREUR PAR SITE ==========\n%s",
        by_site[
            [
                "RMSE",
                "R2",
                "nRMSE_%",
            ]
        ]
        .round(4)
        .to_string(),
    )

    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    by_site.to_csv(
        REPORTS_DIR
        / "v14_errors_by_site.csv",
    )

    # --------------------------------------------------------------
    # Jour / nuit
    # --------------------------------------------------------------

    day = (
        test_meta["is_day"]
        .astype(bool)
        .to_numpy()
    )

    day_active = (
        day
        & (
            test_meta["y_true"].to_numpy()
            > MAPE_THRESHOLD_MW
        )
    )

    day_night_rows = []

    for label, mask in [
        ("nuit", ~day),
        ("jour", day),
        ("jour_actif", day_active),
    ]:

        metrics = compute_metrics(
            test_meta.loc[mask, "y_true"],
            test_meta.loc[mask, "y_pred"],
        )

        metrics["regime"] = label

        day_night_rows.append(
            metrics
        )

    day_night_df = (
        pd.DataFrame(
            day_night_rows
        )
        .set_index("regime")
    )

    day_night_df.to_csv(
        REPORTS_DIR
        / "v14_errors_day_night.csv",
    )

    logger.info(
        "\n========== MAE JOUR / NUIT ==========\n%s",
        day_night_df[
            [
                "MAE",
                "RMSE",
                "n_samples",
            ]
        ]
        .round(4)
        .to_string(),
    )

    # --------------------------------------------------------------
    # Mensuel
    # --------------------------------------------------------------

    monthly_rows = []

    for (month, site), group in (
        test_meta
        .groupby(["month", "site_id"])
    ):

        metrics = compute_metrics(
            group["y_true"],
            group["y_pred"],
            capacity=capacity_map[site],
        )

        metrics["month"] = month
        metrics["site_id"] = site

        monthly_rows.append(
            metrics
        )

    monthly_df = (
        pd.DataFrame(
            monthly_rows
        )
        .set_index(
            ["site_id", "month"]
        )
        .sort_index()
    )

    monthly_df.to_csv(
        REPORTS_DIR
        / "v14_errors_monthly.csv",
    )

    # --------------------------------------------------------------
    # Par heure de la journée
    # --------------------------------------------------------------

    hourly_rows = []

    for hour, group in (
        test_meta
        .groupby("hour")
    ):

        metrics = compute_metrics(
            group["y_true"],
            group["y_pred"],
        )

        metrics["hour"] = hour

        hourly_rows.append(
            metrics
        )

    hourly_df = (
        pd.DataFrame(
            hourly_rows
        )
        .set_index("hour")
        .sort_index()
    )

    hourly_df.to_csv(
        REPORTS_DIR
        / "v14_errors_hourly.csv",
    )

    # --------------------------------------------------------------
    # Train vs CV vs holdout
    # --------------------------------------------------------------

    train_idx, _ = (
        final_split_indices(df)
    )

    train_pred = _predict_refit(
        best_name,
        fitted,
        X.iloc[train_idx],
    )

    train_metrics = compute_metrics(
        y[train_idx],
        train_pred,
    )

    overfit = pd.DataFrame(
        {
            "RMSE": [
                train_metrics["RMSE"],
                hpo_results[
                    best_name
                ]["best_cv_rmse"],
                comparison.loc[
                    best_name,
                    "RMSE",
                ],
            ],

            "R2": [
                train_metrics["R2"],
                np.nan,
                comparison.loc[
                    best_name,
                    "R2",
                ],
            ],
        },

        index=[
            "train",
            "CV",
            "holdout",
        ],
    )

    logger.info(
        "\n========== TRAIN / CV / HOLDOUT ==========\n%s",
        overfit
        .round(4)
        .to_string(),
    )

    overfit.to_csv(
        REPORTS_DIR
        / "v14_train_cv_holdout.csv",
    )

    return (
        by_site,
        day_night_df,
        monthly_df,
        hourly_df,
        overfit,
    )


# ============================================================================
# 28. BENCHMARK PERSISTANCE
# ============================================================================

def persistence_baseline(
    df,
    test_idx,
):
    """
    Baseline naive : production prévue = production de la veille
    à la même heure (shift de 24h par site).
    """

    tmp = df[
        [
            "timestamp",
            "site_id",
            "production_mw",
            "is_day",
        ]
    ].copy()

    tmp = (
        tmp
        .sort_values(
            ["site_id", "timestamp"]
        )
    )

    tmp["prev_day"] = (
        tmp
        .groupby("site_id")["production_mw"]
        .shift(24)
    )

    test = tmp.iloc[
        test_idx
    ].copy()

    mask = (
        test["prev_day"].notna()
        & test["production_mw"].notna()
    )

    test = test.loc[mask]

    capacity_map = build_capacity_map()

    metrics = compute_global_metrics(
        test,
        test["production_mw"],
        test["prev_day"],
        capacity_map,
    )

    day = (
        test["is_day"]
        .astype(bool)
        .to_numpy()
    )

    day_metrics = compute_metrics(
        test.loc[day, "production_mw"],
        test.loc[day, "prev_day"],
    )

    result = {
        "persistence_24h_metrics": metrics,
        "persistence_24h_daytime_MAE": (
            day_metrics["MAE"]
        ),
    }

    logger.info(
        "\n========== BENCHMARK PERSISTANCE J-1 ==========\n"
        "RMSE=%.4f | MAE=%.4f | R2=%.4f | MAE jour=%.4f",
        metrics["RMSE"],
        metrics["MAE"],
        metrics["R2"],
        day_metrics["MAE"],
    )

    return result


# ============================================================================
# 29. EXPORT MODELE FINAL
# ============================================================================

def export_bundle(
    df,
    X,
    y,
    hpo_results,
    decision,
    top_models,
    weights,
    decision_metrics,
    comparison,
    baseline,
    data_hash,
):

    import joblib

    from sklearn.neural_network import (
        MLPRegressor,
    )

    from sklearn.preprocessing import (
        StandardScaler,
    )

    def fit_final_member(
        name,
        best_params,
    ):

        # --------------------------------------------------------------
        # MLP
        # --------------------------------------------------------------

        if name == "mlp":

            scaler = (
                StandardScaler()
                .fit(X)
            )

            arch_options = [
                (64,),
                (128,),
                (64, 32),
                (128, 64),
                (128, 64, 32),
            ]

            arch = (
                arch_options[
                    best_params[
                        "arch_idx"
                    ]
                ]
            )

            model = MLPRegressor(
                hidden_layer_sizes=arch,
                alpha=best_params[
                    "alpha"
                ],
                learning_rate_init=
                    best_params[
                        "learning_rate_init"
                    ],
                early_stopping=True,
                n_iter_no_change=15,
                max_iter=300,
                validation_fraction=0.15,
                random_state=RANDOM_SEED,
            )

            model.fit(
                scaler.transform(X),
                y,
            )

            return model, scaler

        # --------------------------------------------------------------
        # Boosting
        # --------------------------------------------------------------

        if name in (
            "xgboost",
            "lightgbm",
            "catboost",
        ):

            params = dict(
                best_params
            )

            if name == "xgboost":

                params.update(
                    n_estimators=300,
                    n_jobs=1,
                    tree_method="hist",
                    random_state=RANDOM_SEED,
                )

            elif name == "lightgbm":

                params.update(
                    n_estimators=300,
                    n_jobs=1,
                    verbosity=-1,
                    random_state=RANDOM_SEED,
                )

            else:

                params.update(
                    iterations=300,
                    thread_count=1,
                    verbose=False,
                    bootstrap_type="Bernoulli",
                    random_seed=RANDOM_SEED,
                    allow_writing_files=False,

                )

            model = build_model(
                name,
                params,
            )

            model.fit(
                X,
                y,
            )

            return model, None

        # --------------------------------------------------------------
        # Autres modèles
        # --------------------------------------------------------------

        model = build_model(
            name,
            best_params,
        )

        model.fit(
            X,
            y,
        )

        return model, None

    # --------------------------------------------------------------
    # Membres finaux
    # --------------------------------------------------------------

    if decision == "mlp":

        member_names = [
            "mlp"
        ]

        member_weights = [
            1.0
        ]

    elif decision.startswith(
        "ensemble"
    ):

        member_names = top_models

        member_weights = [
            weights[name]
            for name in top_models
        ]

    else:

        member_names = [
            decision
        ]

        member_weights = [
            1.0
        ]

    members = []

    for name in member_names:

        model, scaler = (
            fit_final_member(
                name,
                hpo_results[
                    name
                ]["best_params"],
            )
        )

        members.append(
            {
                "name": name,
                "model": model,
                "scaler": scaler,
            }
        )

    # --------------------------------------------------------------
    # Bundle
    # --------------------------------------------------------------

    cv_summary = {}

    for name in member_names:

        cv_summary[name] = (
            hpo_results[name]
            ["best_cv_rmse"]
        )

    bundle = {

        "final_choice": decision,

        "selection_policy": (
            "CV walk-forward uniquement; "
            "holdout réservé au rapport"
        ),

        "members": members,

        "weights": member_weights,

        "feature_columns": list(
            X.columns
        ),

        "site_coords": SITE_COORDS,

        "timezone": TZ,

        "capacity_map_mw":
            build_capacity_map(),

        "mape_threshold_mw":
            MAPE_THRESHOLD_MW,

        "cv_metrics": cv_summary,

        "holdout_test_metrics":
            dict(
                decision_metrics
            ),

        "baseline_persistence":
            baseline,

        "training_data_range": [
            str(
                df["timestamp"].min()
            ),
            str(
                df["timestamp"].max()
            ),
        ],

        "data_hash": data_hash,

        "no_time_shift": True,

        "timestamp_policy":
            "timestamps unchanged; "
            "Africa/Tunis used only by pvlib",
    }

    MODELS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        MODELS_DIR
        / "final_model_bundle.joblib"
    )

    joblib.dump(
        bundle,
        output_path,
    )

    logger.info(
        "Modèle final exporté : %s",
        output_path,
    )

    logger.info(
        "Membres : %s",
        member_names,
    )

    logger.info(
        "Poids : %s",
        [
            round(w, 3)
            for w in member_weights
        ],
    )

    logger.info(
        "Features : %d",
        len(
            bundle[
                "feature_columns"
            ]
        ),
    )

    return bundle


# ============================================================================
# 30. PREDICTION
# ============================================================================

def predict_production(
    weather_forecast_df: pd.DataFrame,
    bundle: dict,
) -> np.ndarray:
    """
    Prévision de production à partir d'une prévision météo.

    weather_forecast_df doit contenir :

        timestamp
        site_id
        WEATHER_COLS
        is_day

    Aucun historique de production n'est nécessaire.
    Aucun décalage horaire n'est appliqué.

    v14 : une feature manquante lève une erreur au lieu d'être
    remplie silencieusement par 0.
    """

    feat = weather_forecast_df.copy()

    feat = validate_timestamps(
        feat
    )

    feat = add_calendar_features(
        feat
    )

    feat = add_solar_geometry(
        feat
    )

    feat = add_physical_features(
        feat
    )

    missing_features = [
        col for col in FINAL_FEATURE_COLS
        if col not in feat.columns
    ]

    if missing_features:

        raise ValueError(
            "Features requises absentes de l'entrée : "
            f"{missing_features}"
        )

    X_new = build_design_matrix(
        feat,
        feature_cols=FINAL_FEATURE_COLS,
    )

    extra_cols = (
        set(X_new.columns)
        - set(bundle["feature_columns"])
    )

    if extra_cols:

        # Site inconnu à l'entraînement : le dummy est ignoré.
        X_new = X_new.drop(
            columns=extra_cols,
        )

    missing_cols = (
        set(bundle["feature_columns"])
        - set(X_new.columns)
    )

    # Les seules colonnes manquantes possibles sont des dummies de
    # site (les features FINAL_FEATURE_COLS sont déjà vérifiées ci-
    # dessus). Ex. : une entrée mono-site → dummies des autres sites = 0.
    for col in sorted(missing_cols):

        X_new[col] = 0.0

    X_new = X_new[
        bundle["feature_columns"]
    ]

    pred = np.zeros(
        len(X_new),
        dtype=float,
    )

    for member, weight in zip(
        bundle["members"],
        bundle["weights"],
    ):

        scaler = member[
            "scaler"
        ]

        model = member[
            "model"
        ]

        if scaler is not None:

            X_input = (
                scaler.transform(
                    X_new
                )
            )

        else:

            X_input = X_new

        pred += (
            weight
            * model.predict(
                X_input
            )
        )

    # Une production PV ne doit pas être négative.
    pred = np.maximum(
        pred,
        0.0,
    )

    # Limite physique par capacité du site
    if "site_id" in feat.columns:

        capacity_map = bundle[
            "capacity_map_mw"
        ]

        capacities = (
            feat["site_id"]
            .map(capacity_map)
            .to_numpy()
        )

        valid_capacity = (
            ~pd.isna(capacities)
        )

        pred[valid_capacity] = np.minimum(
            pred[valid_capacity],
            capacities[
                valid_capacity
            ],
        )

    return pred


# ============================================================================
# 31. DEMO
# ============================================================================

def run_demo(
    df,
    bundle,
):

    _, test_idx = (
        final_split_indices(df)
    )

    demo_idx = test_idx[
        : min(
            48,
            len(test_idx),
        )
    ]

    if len(demo_idx) == 0:
        return

    demo = df.iloc[
        demo_idx
    ].copy()

    demo_pred = (
        predict_production(
            demo,
            bundle,
        )
    )

    result = pd.DataFrame(
        {
            "timestamp":
                demo["timestamp"].values,

            "site_id":
                demo["site_id"].values,

            "production_reelle_mw":
                demo[
                    "production_mw"
                ].values,

            "production_predite_mw":
                np.round(
                    demo_pred,
                    3,
                ),
        }
    )

    logger.info(
        "\n========== DEMO 48H ==========\n%s",
        result.head(10)
        .to_string(index=False),
    )


# ============================================================================
# 32. MAIN
# ============================================================================

def main(
    skip_hpo=False,
    quick=False,
    models_dir: str | None = None,
):

    global MODELS_DIR

    if models_dir:

        MODELS_DIR = Path(
            models_dir
        )

    t_start = time.time()

    warnings.filterwarnings(
        "ignore"
    )

    random.seed(
        RANDOM_SEED
    )

    np.random.seed(
        RANDOM_SEED
    )

    for directory in (
        FINAL_DIR,
        MODELS_DIR,
        REPORTS_DIR,
        FIGURES_DIR,
    ):

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    logger.info(
        "=================================================="
    )

    logger.info(
        "STEG HelioCast AI - Pipeline v14"
    )

    logger.info(
        "Modèles : %s",
        MODELS_DIR,
    )

    logger.info(
        "Rapports : %s",
        REPORTS_DIR,
    )

    logger.info(
        "Timezone pvlib : %s | Décalage : AUCUN",
        TZ,
    )

    # --------------------------------------------------------------
    # 1. Prétraitement
    # --------------------------------------------------------------

    ready = (
        build_modeling_ready_dataset()
    )

    # --------------------------------------------------------------
    # 2. Feature engineering
    # --------------------------------------------------------------

    df = build_feature_dataset(
        ready
    )

    # --------------------------------------------------------------
    # 3. Design matrix
    # --------------------------------------------------------------

    X = build_design_matrix(
        df
    )

    y = df[
        "production_mw"
    ].to_numpy(
        dtype=float
    )

    logger.info(
        "Design matrix : %s",
        X.shape,
    )

    data_hash = compute_data_hash(
        X,
        y
    )

    # --------------------------------------------------------------
    # 4. Splits
    # --------------------------------------------------------------

    all_folds = list(
        cv_split_indices(
            df
        )
    )

    train_idx, test_idx = (
        final_split_indices(df)
    )

    logger.info(
        "Train final (< %s) : %d lignes",
        HOLDOUT_START,
        len(train_idx),
    )

    logger.info(
        "Holdout (>= %s) : %d lignes",
        HOLDOUT_START,
        len(test_idx),
    )

    # --------------------------------------------------------------
    # 5. HPO
    # --------------------------------------------------------------

    if not all_folds:
        raise RuntimeError(
            "Aucun fold CV valide n'a été construit. "
            "Vérifier les timestamps et les périodes CV_FOLDS."
        )

    if skip_hpo:

        hpo_results = {}

        for name in MODEL_SPECS:

            path = (
                MODELS_DIR
                / f"hpo_{name}.json"
            )

            if not path.exists():
                continue

            with open(
                path,
                "r",
                encoding="utf-8",
            ) as f:

                cached = json.load(f)

            if cached.get(
                "data_hash"
            ) != data_hash:

                logger.warning(
                    "Cache %s obsolète (hash différent) - ignoré.",
                    name,
                )

                continue

            hpo_results[name] = cached

        missing = [
            name
            for name in MODEL_SPECS
            if name not in hpo_results
        ]

        if missing:

            raise FileNotFoundError(
                "Cache Optuna manquant ou obsolète pour : "
                f"{missing}. "
                "Lancer sans --skip-hpo."
            )

    else:

        hpo_results = run_hpo(
            X,
            y,
            all_folds,
            quick=quick,
        )

    # --------------------------------------------------------------
    # 6. RMSE par fold (meilleurs paramètres)
    # --------------------------------------------------------------

    evaluate_best_params_on_folds(
        X,
        y,
        all_folds,
        hpo_results,
    )

    # --------------------------------------------------------------
    # 7. Holdout (rapport uniquement)
    # --------------------------------------------------------------

    (
        fitted,
        comparison,
        preds,
        test_data,
    ) = compare_models_on_holdout(
        df,
        X,
        y,
        hpo_results,
    )

    X_test, y_test = test_data

    test_meta = df.iloc[
        test_idx
    ].copy()

    # --------------------------------------------------------------
    # 8. Sélection finale sur CV
    # --------------------------------------------------------------

    (
        weights,
        top_models,
        gain_pct,
        decision,
        decision_metrics,
    ) = select_final_model(
        hpo_results,
        preds,
        y_test,
        test_meta,
    )

    # --------------------------------------------------------------
    # 9. Benchmark persistance
    # --------------------------------------------------------------

    baseline = persistence_baseline(
        df,
        test_idx,
    )

    # --------------------------------------------------------------
    # 10. SHAP
    # --------------------------------------------------------------

    best_name = (
        comparison["RMSE"]
        .idxmin()
    )

    explain_model(
        fitted,
        best_name,
        X_test,
    )

    # --------------------------------------------------------------
    # 11. Erreurs (CSV sauvegardés)
    # --------------------------------------------------------------

    analyze_errors(
        df,
        best_name,
        fitted,
        preds,
        X_test,
        y_test,
        comparison,
        X,
        y,
        hpo_results,
    )

    # --------------------------------------------------------------
    # 12. Export
    # --------------------------------------------------------------

    bundle = export_bundle(
        df,
        X,
        y,
        hpo_results,
        decision,
        top_models,
        weights,
        decision_metrics,
        comparison,
        baseline,
        data_hash,
    )

    # --------------------------------------------------------------
    # 13. Demo
    # --------------------------------------------------------------

    run_demo(
        df,
        bundle,
    )

    logger.info(
        "=================================================="
    )

    logger.info(
        "Pipeline v14 terminé en %.0f secondes.",
        time.time() - t_start,
    )

    logger.info(
        "Modèle final : %s",
        decision,
    )

    logger.info(
        "Rapports : %s",
        REPORTS_DIR,
    )

    logger.info(
        "=================================================="
    )


# ============================================================================
# 33. CLI
# ============================================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "Pipeline de modélisation "
            "PV STEG v14"
        )
    )

    parser.add_argument(
        "--skip-hpo",
        action="store_true",
        help=(
            "Réutilise les caches Optuna "
            "existants (invalidés par hash)."
        ),
    )

    parser.add_argument(
        "--quick",
        action="store_true",
        help=(
            "Mode rapide : "
            "2 essais Optuna maximum "
            "par modèle."
        ),
    )

    parser.add_argument(
        "--models-dir",
        default=None,
        help=(
            "Dossier de sortie des modèles "
            "(défaut : models_final_14)."
        ),
    )

    args = parser.parse_args()

    main(
        skip_hpo=args.skip_hpo,
        quick=args.quick,
        models_dir=args.models_dir,
    )