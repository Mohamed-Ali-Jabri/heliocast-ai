"""
STEG HelioCast AI - Pipeline de modélisation
============================================

Prévision horaire de la production photovoltaïque
pour les centrales STEG.

Pipeline :

    Production nettoyée
            +
    Open-Meteo Historical Forecast
            |
            v
    merged_all_sites.csv
            |
            v
    Nettoyage / contrôle qualité
            |
            v
    Géométrie solaire PVLIB
            |
            v
    Features météo + physiques + calendrier
            |
            v
    HPO Optuna
            |
            v
    Validation walk-forward
            |
            v
    Holdout temporel
            |
            v
    Modèle / Ensemble
            |
            v
    final_model_bundle.joblib

IMPORTANT
---------
Aucun décalage horaire artificiel n'est appliqué.

Le timestamp reste exactement celui fourni par le dataset merged.

Africa/Tunis est utilisé uniquement pour interpréter les timestamps
lors du calcul de la position solaire avec pvlib.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import time
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pvlib
import yaml


# ============================================================================
# 1. CONFIGURATION
# ============================================================================

RANDOM_SEED = 42

# Fuseau utilisé UNIQUEMENT pour pvlib.
TZ = "Africa/Tunis"

# Seuil MAPE
MAPE_THRESHOLD_MW = 0.5

# Interpolation météo uniquement sur petits trous
SHORT_GAP_LIMIT_H = 3

# Heure SCADA considérée peu fiable
MIN_VALID_MINUTES = 30

# --------------------------------------------------------------------------
# Chemins
# --------------------------------------------------------------------------

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
MODELS_DIR = PROJECT_ROOT / "models_final_13"
FIGURES_DIR = PROJECT_ROOT / "figures"


# ============================================================================
# LOGGER
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


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

# latitude, longitude, altitude
#
# Les coordonnées viennent de ton projet.
#
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


# ============================================================================
# 5. CHARGEMENT CONFIGURATION SITES
# ============================================================================

def load_sites_config() -> dict:
    """
    Charge config/sites.yaml.

    Retourne :

        {
            site_id: {
                ...
            }
        }
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
    Construit :

        site_id -> capacité MW

    depuis sites.yaml.
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
    """
    Charge merged_all_sites.csv.

    Aucun décalage horaire n'est appliqué.
    """

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

    Optionnel.
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
            "Colonnes qualité absentes : %s",
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

    IMPORTANT :
    aucun +1h / -1h n'est effectué.

    Le timestamp reste inchangé.
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

    # Vérification fréquence
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

    IMPORTANT :

    - production_mw n'est JAMAIS interpolée ;
    - seules les variables météo sont interpolées ;
    - interpolation limitée à 3 heures ;
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

        df["is_low_confidence_reading"] = (
            df["n_valid_minutes"]
            < MIN_VALID_MINUTES
        )

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

    # ------------------------------------------------------------------
    # Dataset réellement utilisé par le modèle
    # ------------------------------------------------------------------

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
    Calcule la position solaire.

    IMPORTANT :

    Le timestamp n'est PAS modifié.

    Exemple :

        timestamp = 12:00

    devient simplement :

        12:00 Africa/Tunis

    pour pvlib.

    Il n'y a aucun +1h.
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

        # --------------------------------------------------------------
        # PAS DE DECALAGE HORAIRE
        # --------------------------------------------------------------

        if timestamps.tz is None:

            ts_local = timestamps.tz_localize(
                TZ
            )

        else:

            ts_local = timestamps.tz_convert(
                TZ
            )

        # --------------------------------------------------------------
        # Position solaire
        # --------------------------------------------------------------

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

        # --------------------------------------------------------------
        # Irradiance extra-terrestre
        # --------------------------------------------------------------

        dni_extra = (
            pvlib.irradiance
            .get_extra_radiation(
                ts_local
            )
        )

        # --------------------------------------------------------------
        # Air mass
        # --------------------------------------------------------------

        airmass = (
            pvlib.atmosphere
            .get_relative_airmass(
                solpos["apparent_zenith"]
            )
        )

        # --------------------------------------------------------------
        # Linke turbidity
        # --------------------------------------------------------------

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

        # --------------------------------------------------------------
        # Clear sky Ineichen
        # --------------------------------------------------------------

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

    # One-hot site
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
# 22. HPO
# ============================================================================

def run_or_load_hpo(
    name,
    objective,
    n_trials,
    timeout,
    X,
    y,
    folds,
):

    import optuna

    MODELS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    cache_path = (
        MODELS_DIR
        / f"hpo_{name}.json"
    )

    if cache_path.exists():

        with open(
            cache_path,
            "r",
            encoding="utf-8",
        ) as f:

            return json.load(f)

    t0 = time.time()

    db_path = (
        MODELS_DIR
        / f"optuna_{name}.db"
    )

    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(
            seed=RANDOM_SEED
        ),
        storage=f"sqlite:///{db_path}",
        study_name=name,
        load_if_exists=True,
    )

    remaining = max(
        0,
        n_trials - len(study.trials),
    )

    if remaining > 0:

        study.optimize(
            lambda trial:
            objective(
                trial,
                X,
                y,
                folds,
            ),
            n_trials=remaining,
            timeout=timeout,
        )

    result = {
        "model": name,
        "best_params": study.best_params,
        "best_cv_rmse": study.best_value,
        "n_trials": len(study.trials),
        "elapsed_sec": (
            time.time() - t0
        ),
    }

    with open(
        cache_path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            result,
            f,
            indent=2,
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
        )

        logger.info(
            "%s | CV RMSE %.4f | %d essais",
            name,
            results[name]["best_cv_rmse"],
            results[name]["n_trials"],
        )

    return results


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

    raise ValueError(
        f"Modèle inconnu : {name}"
    )


# ============================================================================
# 24. COMPARAISON HOLDOUT
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

    # --------------------------------------------------------------
    # Validation interne pour early stopping
    # --------------------------------------------------------------

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

        metrics = compute_metrics(
            y_test,
            pred_test,
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

        metrics = compute_metrics(
            y_test,
            pred_test_mlp,
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
        "\n========== HOLDOUT ==========\n%s",
        comparison[
            [
                "RMSE",
                "R2",
                "MAPE_daytime_%",
            ]
        ]
        .round(4)
        .to_string(),
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
# 25. ENSEMBLE
# ============================================================================

def build_ensemble(
    comparison,
    hpo_results,
    preds,
    y_test,
):

    top_n = min(
        3,
        len(comparison),
    )

    top_models = (
        comparison.index[
            :top_n
        ]
        .tolist()
    )

    weights = {}

    for model_name in top_models:

        cv_rmse = (
            hpo_results[
                model_name
            ]["best_cv_rmse"]
        )

        weights[model_name] = (
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

    ensemble_pred = sum(
        weights[name]
        * preds[name]
        for name in top_models
    )

    ensemble_metrics = (
        compute_metrics(
            y_test,
            ensemble_pred,
        )
    )

    best_model = (
        comparison["RMSE"]
        .idxmin()
    )

    best_rmse = comparison.loc[
        best_model,
        "RMSE",
    ]

    gain_pct = (
        (
            best_rmse
            - ensemble_metrics["RMSE"]
        )
        / best_rmse
        * 100
    )

    if gain_pct > 2.0:

        decision = (
            "ensemble("
            + "+".join(top_models)
            + ")"
        )

    else:

        decision = best_model

    logger.info(
        "Ensemble : %s",
        {
            name: round(weight, 3)
            for name, weight
            in weights.items()
        },
    )

    logger.info(
        "Meilleur modèle : %s | RMSE %.4f",
        best_model,
        best_rmse,
    )

    logger.info(
        "Ensemble RMSE : %.4f | Gain %.2f%%",
        ensemble_metrics["RMSE"],
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
        ensemble_metrics,
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
# 27. ANALYSE ERREURS
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
            "clearsky_index",
        ],
    ].copy()

    test_meta["y_true"] = y_test
    test_meta["y_pred"] = pred_best
    test_meta["residual"] = (
        pred_best - y_test
    )

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

    return by_site, overfit


# ============================================================================
# 28. EXPORT MODELE FINAL
# ============================================================================

def export_bundle(
    df,
    X,
    y,
    hpo_results,
    decision,
    top_models,
    weights,
    ensemble_metrics,
    comparison,
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

    bundle = {

        "final_choice": decision,

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

        "holdout_test_metrics": (
            comparison.loc[
                decision
            ].to_dict()
            if (
                decision != "mlp"
                and not decision.startswith(
                    "ensemble"
                )
            )
            else dict(
                ensemble_metrics
            )
        ),

        "training_data_range": [
            str(
                df["timestamp"].min()
            ),
            str(
                df["timestamp"].max()
            ),
        ],

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
# 29. PREDICTION
# ============================================================================

def predict_production(
    weather_forecast_df: pd.DataFrame,
    bundle: dict,
) -> np.ndarray:
    """
    Prévision de production à partir d'une prévision météo.

    weather_forecast_df doit contenir au minimum :

        timestamp
        site_id
        WEATHER_COLS
        is_day

    Aucun historique de production n'est nécessaire.

    Aucun décalage horaire n'est appliqué.
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

    X_new = build_design_matrix(
        feat,
        feature_cols=FINAL_FEATURE_COLS,
    )

    X_new = X_new.reindex(
        columns=bundle[
            "feature_columns"
        ],
        fill_value=0.0,
    )

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
# 30. DEMO
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
# 31. MAIN
# ============================================================================

def main(
    skip_hpo=False,
    quick=False,
):

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
        "STEG HelioCast AI"
    )

    logger.info(
        "Pipeline de modélisation PV"
    )

    logger.info(
        "=================================================="
    )

    logger.info(
        "Timezone pvlib : %s",
        TZ,
    )

    logger.info(
        "Décalage horaire : AUCUN"
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

                hpo_results[name] = (
                    json.load(f)
                )

        missing = [
            name
            for name in MODEL_SPECS
            if name not in hpo_results
        ]

        if missing:

            raise FileNotFoundError(
                "Cache Optuna manquant pour : "
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
    # 6. Holdout
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

    # --------------------------------------------------------------
    # 7. Ensemble
    # --------------------------------------------------------------

    (
        weights,
        top_models,
        gain_pct,
        decision,
        ensemble_metrics,
    ) = build_ensemble(
        comparison,
        hpo_results,
        preds,
        y_test,
    )

    # --------------------------------------------------------------
    # 8. SHAP
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
    # 9. Erreurs
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
    # 10. Export
    # --------------------------------------------------------------

    bundle = export_bundle(
        df,
        X,
        y,
        hpo_results,
        decision,
        top_models,
        weights,
        ensemble_metrics,
        comparison,
    )

    # --------------------------------------------------------------
    # 11. Demo
    # --------------------------------------------------------------

    run_demo(
        df,
        bundle,
    )

    logger.info(
        "=================================================="
    )

    logger.info(
        "Pipeline terminé en %.0f secondes.",
        time.time() - t_start,
    )

    logger.info(
        "Modèle final : %s",
        decision,
    )

    logger.info(
        "=================================================="
    )


# ============================================================================
# 32. CLI
# ============================================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "Pipeline de modélisation "
            "PV STEG"
        )
    )

    parser.add_argument(
        "--skip-hpo",
        action="store_true",
        help=(
            "Réutilise les caches Optuna "
            "existants."
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

    args = parser.parse_args()

    main(
        skip_hpo=args.skip_hpo,
        quick=args.quick,
    )