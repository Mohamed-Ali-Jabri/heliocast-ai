"""
STEG HelioCast AI - Pipeline de modélisation
============================================
Prévision horaire de la production photovoltaïque (J+1 à J+7) pour 6 centrales STEG.

Contrainte de déploiement (anti-fuite) :
    - Le modèle n'utilise QUE des données disponibles au moment de la prévision :
      prévisions météo, variables calendaires et astronomie.
    - Tout historique de production (lags, moyennes, persistence) est INTERDIT.

Par rapport au notebook d'origine, cette version :
    - retire cos_aoi / is_tracker (paramètres tilt/azimut indisponibles),
    - corrige add_solar_geometry (qui retournait un DataFrame vide),
    - corrige l'explicabilité SHAP pour HistGradientBoosting,
    - structure le code en modules lisibles (une fonction par étape).

Exécution :
    python scripts/modeling.py                # pipeline complet
    python scripts/modeling.py --skip-hpo     # réutilise le cache Optuna existant
    python scripts/modeling.py --quick        # mini-pipeline de validation rapide
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pvlib

# --------------------------------------------------------------------------- #
# 1. CONFIGURATION & REPRODUCTIBILITE
# --------------------------------------------------------------------------- #

RANDOM_SEED = 42
TZ = "Africa/Tunis"
INSTALLED_CAPACITY_MW = 10.0
MAPE_THRESHOLD_MW = 0.5

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
MERGE_PATH = DATA_DIR / "merged" / "GLOBAL" / "merged_all_sites.csv"
QUALITY_PATH = DATA_DIR / "production_cleaned" / "cleaned_hourly" / "production_hourly_all_sites.csv"
FINAL_DIR = DATA_DIR / "final_data"
MODELS_DIR = PROJECT_ROOT / "models_final"
FIGURES_DIR = PROJECT_ROOT / "figures"

WEATHER_COLS = [
    "shortwave_radiation", "direct_normal_irradiance", "direct_radiation",
    "diffuse_radiation", "temperature_2m", "wind_speed_10m", "cloud_cover",
    "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "relative_humidity_2m", "visibility", "precipitation",
]

SHORT_GAP_LIMIT_H = 3      # interpolation météo sur trous courts uniquement
MIN_VALID_MINUTES = 30     # < 50% de l'heure mesurée -> moyenne horaire peu fiable

# Coordonnées GPS des centrales (config/sites.yaml) + altitude estimée (Google Earth)
SITE_COORDS = {
    "tozeur_1": (33.90859854822346, 8.046303098866254, 154),
    "tozeur_2": (33.90859854822346, 8.046303098866254, 154),
    "feriana_csfb": (34.88905006548165, 8.552969431357354, 696),
    "feriana_csfc": (34.88920040927399, 8.55338789575548, 696),
    "elmourabitine_eni": (33.0502272570142, 10.463332301292539, 177),
    "meknassi_eppm": (34.60536489121733, 9.60224390009452, 257),
}

CV_FOLDS = [
    ("2024-01-01", "2024-04-01"),   # fold 1 : entraînement < 2024-01, val 2024 T1
    ("2024-04-01", "2024-07-01"),
    ("2024-07-01", "2024-10-01"),
    ("2024-10-01", "2025-01-01"),
    ("2025-01-01", "2025-04-01"),
]
HOLDOUT_START = "2025-07-01"

# --------------------------------------------------------------------------- #
# 2. PRETRAITEMENT
# --------------------------------------------------------------------------- #


def load_raw_data() -> pd.DataFrame:
    """Charge le fichier fusionné météo + production (lecture seule)."""
    return pd.read_csv(MERGE_PATH, parse_dates=["timestamp"])


def load_quality_signal() -> pd.DataFrame | None:
    """Récupère n_valid_minutes / production_mw_std (optionnel, dégradation gracieuse)."""
    if not QUALITY_PATH.exists():
        print(f"[info] Signal qualité absent ({QUALITY_PATH}) -> étape 4 ignorée.")
        return None
    quality = pd.read_csv(QUALITY_PATH, parse_dates=["timestamp"])
    return quality[["site_id", "timestamp", "n_valid_minutes", "production_mw_std"]]


def reindex_and_interpolate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Grille horaire complète par site.
    Seules les variables météo sont interpolées, sur des trous <= 3h.
    La cible (production_mw) n'est JAMAIS interpolée.
    """
    frames = []
    for site, group in df.groupby("site_id", sort=False):
        group = group.sort_values("timestamp").set_index("timestamp")
        full_index = pd.date_range(group.index.min(), group.index.max(), freq="h")
        group = group.reindex(full_index)
        group.index.name = "timestamp"
        group["site_id"] = site
        group["timezone"] = group["timezone"].ffill().bfill()
        group[WEATHER_COLS] = group[WEATHER_COLS].interpolate(
            method="time", limit=SHORT_GAP_LIMIT_H, limit_area="inside"
        )
        frames.append(group.reset_index())
    return pd.concat(frames, ignore_index=True)


def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Variables calendaires + encodages cycliques."""
    ts = df["timestamp"]
    df["hour"] = ts.dt.hour
    df["day_of_week"] = ts.dt.dayofweek
    df["month"] = ts.dt.month
    df["day_of_year"] = ts.dt.dayofyear
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    return df


def apply_corrections(df: pd.DataFrame, quality: pd.DataFrame | None) -> pd.DataFrame:
    """Bruit nocturne, arrêts non prévisibles, heures SCADA peu fiables."""
    df = df.copy()

    # is_day manquant -> dérivé de la radiation
    if df["is_day"].isna().any():
        df["is_day"] = df["is_day"].fillna((df["shortwave_radiation"] > 0).astype(float))
    df["is_day"] = df["is_day"].astype("Int64")

    # Correction 2 : bruit capteur nocturne
    night_noise = (df["is_day"] == 0) & (df["production_mw"] > 0)
    df["night_noise_clipped"] = night_noise
    df.loc[night_noise, "production_mw"] = 0.0

    # Correction 3 : arrêt non expliqué par la météo (soleil présent, production nulle)
    outage = (df["is_day"] == 1) & (df["shortwave_radiation"] > 50) & (df["production_mw"] == 0)
    df["is_outage_flag"] = outage
    df["capacity_factor"] = df["production_mw"] / INSTALLED_CAPACITY_MW

    # Correction 4 : heures peu fiables SCADA (n_valid_minutes < 30)
    if quality is not None:
        df = df.merge(quality, on=["site_id", "timestamp"], how="left")
        df["is_low_confidence_reading"] = df["n_valid_minutes"] < MIN_VALID_MINUTES
        df["is_low_confidence_reading"] = df["is_low_confidence_reading"].fillna(False)
    else:
        df["n_valid_minutes"] = np.nan
        df["production_mw_std"] = np.nan
        df["is_low_confidence_reading"] = False

    return df


def build_modeling_ready_dataset() -> pd.DataFrame:
    """Pipeline de prétraitement complet, retourne le dataset prêt pour les features."""
    raw = load_raw_data()
    quality = load_quality_signal()

    clean = reindex_and_interpolate(raw)
    clean = add_calendar_features(clean)
    clean = apply_corrections(clean, quality)

    report = {
        "rows_raw": len(raw),
        "rows_after_reindex": len(clean),
        "rows_added_by_reindex": len(clean) - len(raw),
        "rows_night_noise_clipped": int(clean["night_noise_clipped"].sum()),
        "rows_outage_excluded": int(clean["is_outage_flag"].sum()),
        "rows_low_confidence_excluded": int(clean["is_low_confidence_reading"].sum()),
    }

    ready = clean[
        clean["production_mw"].notna()
        & ~clean[WEATHER_COLS].isna().any(axis=1)
        & ~clean["is_outage_flag"]
        & ~clean["is_low_confidence_reading"]
    ].reset_index(drop=True)
    report["rows_modeling_ready"] = len(ready)

    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    clean.to_csv(FINAL_DIR / "steg_pv_clean_full.csv", index=False)
    ready.to_csv(FINAL_DIR / "steg_pv_modeling_ready.csv", index=False)

    print("--- Prétraitement ---")
    for key, value in report.items():
        print(f"  {key:30s}: {value}")
    return ready


# --------------------------------------------------------------------------- #
# 3. FEATURE ENGINEERING (géométrie solaire + variables physiques)
# --------------------------------------------------------------------------- #


def add_solar_geometry(df: pd.DataFrame) -> pd.DataFrame:
    """
    Position du soleil + irradiance ciel clair théorique (modèle Ineichen).
    Astronomie pure -> connue exactement à l'avance, deployment-safe.

    IMPORTANT : conserve l'ordre des lignes d'entrée. Le calcul groupe en
    interne par site puis trie par timestamp (nécessaire pour pvlib), mais
    sans restauration de l'ordre d'origine, un DataFrame multi-sites non
    trié globalement par timestamp (ex : un batch d'inférence mélangeant
    plusieurs centrales) ressortirait réordonné site-par-site -> les
    prédictions calculées en aval seraient associées aux mauvaises lignes
    (timestamp/site_id) lors du réassemblage. D'où le sort_index() final.
    """
    df = df.reset_index(drop=True)  # index propre et unique à restaurer ensuite
    frames = []
    for site, group in df.groupby("site_id", sort=False):
        lat, lon, elevation = SITE_COORDS[site]
        group = group.sort_values("timestamp").copy()
        ts_raw = pd.DatetimeIndex(group["timestamp"])
        ts_local = ts_raw.tz_localize(TZ) if ts_raw.tz is None else ts_raw.tz_convert(TZ)

        solpos = pvlib.solarposition.get_solarposition(ts_local, lat, lon, altitude=elevation)
        group["solar_zenith"] = solpos["apparent_zenith"].values
        group["solar_elevation"] = solpos["apparent_elevation"].values
        group["solar_azimuth"] = solpos["azimuth"].values

        dni_extra = pvlib.irradiance.get_extra_radiation(ts_local)
        airmass = pvlib.atmosphere.get_relative_airmass(solpos["apparent_zenith"])
        try:
            linke = pvlib.clearsky.lookup_linke_turbidity(ts_local, lat, lon)
        except Exception:
            linke = pd.Series(3.0, index=ts_local)

        clearsky = pvlib.clearsky.ineichen(
            solpos["apparent_zenith"], airmass, linke, altitude=elevation, dni_extra=dni_extra
        )
        group["clearsky_ghi"] = clearsky["ghi"].values
        group["clearsky_dni"] = clearsky["dni"].values
        group["clearsky_dhi"] = clearsky["dhi"].values
        frames.append(group)

    return pd.concat(frames).sort_index()


def add_physical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Indices physiques issus de la littérature de prévision PV."""
    df = df.copy()

    # Clear-sky index : atténuation nuageuse, isolée de la géométrie solaire
    clearsky_ghi = df["clearsky_ghi"].clip(lower=1e-3)
    df["clearsky_index"] = (df["shortwave_radiation"] / clearsky_ghi).clip(0, 1.5)
    df.loc[df["solar_elevation"] <= 0, "clearsky_index"] = 0.0

    # Proxy température de cellule (NOCT ~45°C) + dératage thermique
    df["cell_temp_proxy"] = df["temperature_2m"] + (45 - 20) / 800 * df["shortwave_radiation"]

    # Terme d'interaction nuages x irradiation
    df["cloud_cover_x_ghi"] = df["cloud_cover"] / 100.0 * df["shortwave_radiation"]

    # Saisonnalité continue (remplace month_sin/cos, plus fin)
    df["doy_sin"] = np.sin(2 * np.pi * df["day_of_year"] / 365.25)
    df["doy_cos"] = np.cos(2 * np.pi * df["day_of_year"] / 365.25)
    return df


def build_feature_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute la géométrie solaire et les variables physiques, puis sauvegarde."""
    t0 = time.time()
    out = add_solar_geometry(df)
    out = add_physical_features(out)
    out = out.sort_values("timestamp").reset_index(drop=True)
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(FINAL_DIR / "steg_pv_features.csv", index=False)
    print(f"--- Feature engineering : {out.shape} en {time.time() - t0:.1f}s ---")
    return out


# --------------------------------------------------------------------------- #
# 4. SELECTION DE FEATURES
# --------------------------------------------------------------------------- #

# Features finales : météo + calendrier + astronomie.
# NB : pas de cos_aoi / is_tracker (paramètres tilt/azimut indisponibles).
FINAL_FEATURE_COLS = [
    "shortwave_radiation", "direct_normal_irradiance", "diffuse_radiation",
    "temperature_2m", "wind_speed_10m", "cloud_cover", "cloud_cover_low",
    "cloud_cover_mid", "cloud_cover_high", "relative_humidity_2m", "visibility",
    "precipitation", "hour", "day_of_week", "hour_sin", "hour_cos", "doy_sin",
    "doy_cos", "is_day", "solar_elevation", "solar_azimuth", "clearsky_dni",
    "clearsky_index", "cell_temp_proxy", "cloud_cover_x_ghi",
]

# Colonnes exclues par construction (fuite de données ou redondance) :
#   - production_mw / capacity_factor            : la cible ou sa reformulation
#   - night_noise_clipped / is_outage_flag / is_low_confidence_reading
#                                               : dérivées de la cible pendant le nettoyage
#   - n_valid_minutes / production_mw_std        : indisponibles en production
#   - timestamp / timezone                       : non numériques
#   - solar_zenith                               : doublon exact de solar_elevation
#   - month / day_of_year / month_sin/cos        : remplacés par doy_sin/cos
#   - direct_radiation, direct_diffuse_ratio     : colinéaires à shortwave/DNI
#   - clearsky_ghi / clearsky_dhi                : gardées en interne pour clearsky_index
#   - thermal_derate_factor                      : déterministe de cell_temp_proxy


def build_design_matrix(data: pd.DataFrame, feature_cols: list[str] | None = None) -> pd.DataFrame:
    """Features + one-hot encoding du site (préprocessing identique train/serving)."""
    cols = feature_cols if feature_cols is not None else FINAL_FEATURE_COLS
    X = data[cols].copy()
    site_dummies = pd.get_dummies(data["site_id"], prefix="site", dtype=float)
    return pd.concat([X, site_dummies], axis=1)


# --------------------------------------------------------------------------- #
# 5. VALIDATION WALK-FORWARD & METRIQUES
# --------------------------------------------------------------------------- #


def cv_split_indices(data: pd.DataFrame):
    """Yields (train_idx, val_idx) pour chaque fold chronologique."""
    ts = data["timestamp"]
    for train_end, val_end in CV_FOLDS:
        train_idx = np.where(ts < train_end)[0]
        val_idx = np.where((ts >= train_end) & (ts < val_end))[0]
        yield train_idx, val_idx


def final_split_indices(data: pd.DataFrame):
    """Train (< holdout) et test (>= holdout), strictement chronologiques."""
    ts = data["timestamp"]
    train_idx = np.where(ts < HOLDOUT_START)[0]
    test_idx = np.where(ts >= HOLDOUT_START)[0]
    return train_idx, test_idx


def compute_metrics(y_true, y_pred, capacity: float = INSTALLED_CAPACITY_MW,
                    mape_threshold_mw: float = MAPE_THRESHOLD_MW) -> dict:
    """MAE, RMSE, R², MAPE (heures de jour, production > seuil), nMAE/nRMSE en %."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    err = y_pred - y_true

    mae = np.mean(np.abs(err))
    rmse = np.sqrt(np.mean(err ** 2))
    ss_res, ss_tot = np.sum(err ** 2), np.sum((y_true - y_true.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan

    mask = y_true > mape_threshold_mw
    mape = (np.mean(np.abs(err[mask] / y_true[mask])) * 100) if mask.sum() > 0 else np.nan

    return {
        "MAE": mae, "RMSE": rmse, "R2": r2, "MAPE_daytime_%": mape,
        "nMAE_%": mae / capacity * 100, "nRMSE_%": rmse / capacity * 100,
        "n_samples": len(y_true),
    }


# --------------------------------------------------------------------------- #
# 6. OPTIMISATION D'HYPERPARAMETRES (Optuna, walk-forward)
# --------------------------------------------------------------------------- #


def _fit_with_early_stop(model, X_train, y_train, X_val, y_val):
    """Appel d'entraînement homogène selon la famille de modèle."""
    name = model.__class__.__name__
    if name == "XGBRegressor":
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    elif name == "LGBMRegressor":
        import lightgbm as lgb
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)],
                  callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(0)])
    elif name == "CatBoostRegressor":
        model.fit(X_train, y_train, eval_set=(X_val, y_val), verbose=False)
    else:
        model.fit(X_train, y_train)
    return model


def _rmse_cv(model_factory, X, y, folds):
    """RMSE moyen sur les folds walk-forward pour un modèle donné."""
    scores = []
    for train_idx, val_idx in folds:
        model = model_factory()
        model = _fit_with_early_stop(model, X.iloc[train_idx], y[train_idx],
                                     X.iloc[val_idx], y[val_idx])
        pred = model.predict(X.iloc[val_idx])
        scores.append(np.sqrt(np.mean((pred - y[val_idx]) ** 2)))
    return float(np.mean(scores))


def _objective_xgboost(trial, X, y, folds):
    import xgboost as xgb
    params = dict(
        n_estimators=1000,
        max_depth=trial.suggest_int("max_depth", 3, 10),
        learning_rate=trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        subsample=trial.suggest_float("subsample", 0.6, 1.0),
        colsample_bytree=trial.suggest_float("colsample_bytree", 0.6, 1.0),
        min_child_weight=trial.suggest_int("min_child_weight", 1, 20),
        reg_alpha=trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
        reg_lambda=trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
        gamma=trial.suggest_float("gamma", 1e-3, 5.0, log=True),
        n_jobs=1, tree_method="hist", early_stopping_rounds=30, random_state=RANDOM_SEED,
    )
    return _rmse_cv(lambda: xgb.XGBRegressor(**params), X, y, folds)


def _objective_lightgbm(trial, X, y, folds):
    import lightgbm as lgb
    params = dict(
        n_estimators=1000,
        max_depth=trial.suggest_int("max_depth", 3, 10),
        num_leaves=trial.suggest_int("num_leaves", 15, 200),
        learning_rate=trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        subsample=trial.suggest_float("subsample", 0.6, 1.0),
        colsample_bytree=trial.suggest_float("colsample_bytree", 0.6, 1.0),
        min_child_samples=trial.suggest_int("min_child_samples", 5, 100),
        reg_alpha=trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
        reg_lambda=trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
        n_jobs=1, verbosity=-1, random_state=RANDOM_SEED,
    )
    return _rmse_cv(lambda: lgb.LGBMRegressor(**params), X, y, folds)


def _objective_catboost(trial, X, y, folds):
    import catboost as cb
    params = dict(
        iterations=1000,
        depth=trial.suggest_int("depth", 3, 10),
        learning_rate=trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        l2_leaf_reg=trial.suggest_float("l2_leaf_reg", 1e-2, 20.0, log=True),
        subsample=trial.suggest_float("subsample", 0.6, 1.0),
        bootstrap_type="Bernoulli", thread_count=1, verbose=False,
        early_stopping_rounds=30, random_seed=RANDOM_SEED,
    )
    return _rmse_cv(lambda: cb.CatBoostRegressor(**params), X, y, folds)


def _objective_histgb(trial, X, y, folds):
    from sklearn.ensemble import HistGradientBoostingRegressor
    params = dict(
        max_iter=trial.suggest_int("max_iter", 100, 600),
        max_depth=trial.suggest_int("max_depth", 3, 12),
        learning_rate=trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        min_samples_leaf=trial.suggest_int("min_samples_leaf", 5, 100),
        l2_regularization=trial.suggest_float("l2_regularization", 1e-3, 10.0, log=True),
        max_leaf_nodes=trial.suggest_int("max_leaf_nodes", 15, 200),
        early_stopping=True, validation_fraction=0.15, n_iter_no_change=20,
        random_state=RANDOM_SEED,
    )
    return _rmse_cv(lambda: HistGradientBoostingRegressor(**params), X, y, folds)


def _objective_extratrees(trial, X, y, folds):
    from sklearn.ensemble import ExtraTreesRegressor
    params = dict(
        n_estimators=trial.suggest_int("n_estimators", 100, 300),
        max_depth=trial.suggest_int("max_depth", 6, 16),
        min_samples_leaf=trial.suggest_int("min_samples_leaf", 2, 30),
        max_features=trial.suggest_float("max_features", 0.4, 1.0),
        n_jobs=1, random_state=RANDOM_SEED,
    )
    return _rmse_cv(lambda: ExtraTreesRegressor(**params), X, y, folds)


def _objective_randomforest(trial, X, y, folds):
    from sklearn.ensemble import RandomForestRegressor
    params = dict(
        n_estimators=trial.suggest_int("n_estimators", 60, 150),
        max_depth=trial.suggest_int("max_depth", 5, 10),
        min_samples_leaf=trial.suggest_int("min_samples_leaf", 5, 40),
        max_features=trial.suggest_float("max_features", 0.4, 1.0),
        max_samples=trial.suggest_float("max_samples", 0.3, 0.7),
        n_jobs=1, random_state=RANDOM_SEED,
    )
    return _rmse_cv(lambda: RandomForestRegressor(**params), X, y, folds)


def _objective_mlp(trial, X, y, folds):
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    arch_options = [(64,), (128,), (64, 32), (128, 64), (128, 64, 32)]
    arch = arch_options[trial.suggest_int("arch_idx", 0, len(arch_options) - 1)]
    alpha = trial.suggest_float("alpha", 1e-5, 1e-1, log=True)
    lr_init = trial.suggest_float("learning_rate_init", 1e-4, 1e-2, log=True)

    scores = []
    for train_idx, val_idx in folds:
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        scaler = StandardScaler().fit(X_train)
        model = MLPRegressor(
            hidden_layer_sizes=arch, alpha=alpha, learning_rate_init=lr_init,
            early_stopping=True, n_iter_no_change=15, max_iter=300,
            validation_fraction=0.15, random_state=RANDOM_SEED,
        )
        model.fit(scaler.transform(X_train), y[train_idx])
        pred = model.predict(scaler.transform(X_val))
        scores.append(np.sqrt(np.mean((pred - y[val_idx]) ** 2)))
    return float(np.mean(scores))


# Espace de recherche + budget par modèle (plafond de temps par recherche)
MODEL_SPECS = {
    "xgboost":      (_objective_xgboost,     20, 240),
    "lightgbm":     (_objective_lightgbm,    20, 180),
    "histgb":       (_objective_histgb,      20, 180),
    "catboost":     (_objective_catboost,    12, 180),
    "extratrees":   (_objective_extratrees,  12, 180),
    "randomforest": (_objective_randomforest, 8, 240),
    "mlp":          (_objective_mlp,         12, 150),
}


def run_or_load_hpo(name: str, objective, n_trials: int, timeout: int,
                    X, y, folds) -> dict:
    """Lance Optuna (cache JSON sur disque) pour un modèle donné."""
    import optuna

    cache_path = MODELS_DIR / f"hpo_{name}.json"
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)

    t0 = time.time()
    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=RANDOM_SEED),
        storage=f"sqlite:///{MODELS_DIR / f'optuna_{name}.db'}",
        study_name=name, load_if_exists=True,
    )
    remaining = max(0, n_trials - len(study.trials))
    if remaining > 0:
        study.optimize(lambda trial: objective(trial, X, y, folds),
                       n_trials=remaining, timeout=timeout)

    result = {
        "model": name,
        "best_params": study.best_params,
        "best_cv_rmse": study.best_value,
        "n_trials": len(study.trials),
        "elapsed_sec": time.time() - t0,
    }
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2)
    return result


def run_hpo(X, y, folds, quick: bool = False) -> dict:
    """Optimisation Optuna de tous les modèles, avec cache."""
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, (objective, n_trials, timeout) in MODEL_SPECS.items():
        if quick:
            n_trials = min(n_trials, 2)
            timeout = min(timeout, 60)
        print(f"Optimisation {name}...", end=" ", flush=True)
        results[name] = run_or_load_hpo(name, objective, n_trials, timeout, X, y, folds)
        print(f"CV RMSE={results[name]['best_cv_rmse']:.4f} "
              f"({results[name]['n_trials']} essais)")
    return results


# --------------------------------------------------------------------------- #
# 7. COMPARAISON DES MODELES SUR LE HOLDOUT
# --------------------------------------------------------------------------- #


def build_model(name: str, best_params: dict):
    """Instancie un modèle avec ses meilleurs hyperparamètres (refit final)."""
    import xgboost as xgb
    import lightgbm as lgb
    import catboost as cb
    from sklearn.ensemble import (RandomForestRegressor, ExtraTreesRegressor,
                                  HistGradientBoostingRegressor)

    if name == "xgboost":
        params = dict(best_params)
        params.update(n_estimators=1000, n_jobs=1, tree_method="hist", random_state=RANDOM_SEED)
        return xgb.XGBRegressor(**params)
    if name == "lightgbm":
        params = dict(best_params)
        params.update(n_estimators=1000, n_jobs=1, verbosity=-1, random_state=RANDOM_SEED)
        return lgb.LGBMRegressor(**params)
    if name == "catboost":
        params = dict(best_params)
        params.update(iterations=1000, thread_count=1, verbose=False,
                      bootstrap_type="Bernoulli", random_seed=RANDOM_SEED)
        return cb.CatBoostRegressor(**params)
    if name == "histgb":
        params = dict(best_params)
        params.update(early_stopping=True, validation_fraction=0.15,
                      n_iter_no_change=20, random_state=RANDOM_SEED)
        return HistGradientBoostingRegressor(**params)
    if name == "extratrees":
        params = dict(best_params)
        params.update(n_jobs=1, random_state=RANDOM_SEED)
        return ExtraTreesRegressor(**params)
    if name == "randomforest":
        params = dict(best_params)
        params.update(n_jobs=1, random_state=RANDOM_SEED)
        return RandomForestRegressor(**params)
    raise ValueError(f"Modèle inconnu : {name}")


def compare_models_on_holdout(df: pd.DataFrame, X, y, hpo_results: dict):
    """
    Refit de chaque modèle sur le train final + évaluation sur le holdout isolé.
    Retourne (fitted_models, comparison_df, pred_test_by_model).
    """
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler

    train_idx, test_idx = final_split_indices(df)
    X_train, y_train = X.iloc[train_idx], y[train_idx]
    X_test, y_test = X.iloc[test_idx], y[test_idx]

    # Tranche de validation interne pour l'early stopping (jamais le test)
    val_cut = df.loc[train_idx, "timestamp"].quantile(0.9)
    es_train_idx = train_idx[df.loc[train_idx, "timestamp"] < val_cut]
    es_val_idx = train_idx[df.loc[train_idx, "timestamp"] >= val_cut]

    fitted, rows = {}, []
    arch_options = [(64,), (128,), (64, 32), (128, 64), (128, 64, 32)]

    for name, res in hpo_results.items():
        if name == "mlp":
            continue

        t0 = time.time()
        model = build_model(name, res["best_params"])
        if name in ("xgboost", "lightgbm", "catboost"):
            model = _fit_with_early_stop(
                model, X.iloc[es_train_idx], y[es_train_idx],
                X.iloc[es_val_idx], y[es_val_idx],
            )
        else:
            model.fit(X_train, y_train)
        train_time = time.time() - t0

        t0 = time.time()
        pred_test = model.predict(X_test)
        infer_time = time.time() - t0

        metrics = compute_metrics(y_test, pred_test)
        metrics.update({"modele": name, "train_time_s": train_time,
                        "infer_rows_per_s": len(X_test) / infer_time})
        rows.append(metrics)
        fitted[name] = model
        print(f"{name:14s} RMSE={metrics['RMSE']:.4f}  R2={metrics['R2']:.4f}  "
              f"nRMSE%={metrics['nRMSE_%']:.2f}  train={train_time:.1f}s")

    # MLP séparément (nécessite un scaler)
    mlp_params = hpo_results["mlp"]["best_params"]
    scaler = StandardScaler().fit(X_train)
    mlp = MLPRegressor(
        hidden_layer_sizes=arch_options[mlp_params["arch_idx"]],
        alpha=mlp_params["alpha"], learning_rate_init=mlp_params["learning_rate_init"],
        early_stopping=True, n_iter_no_change=15, max_iter=300,
        validation_fraction=0.15, random_state=RANDOM_SEED,
    )
    t0 = time.time()
    mlp.fit(scaler.transform(X_train), y_train)
    train_time = time.time() - t0

    t0 = time.time()
    pred_test_mlp = mlp.predict(scaler.transform(X_test))
    infer_time = time.time() - t0

    metrics = compute_metrics(y_test, pred_test_mlp)
    metrics.update({"modele": "mlp", "train_time_s": train_time,
                    "infer_rows_per_s": len(X_test) / infer_time})
    rows.append(metrics)
    fitted["mlp"] = (mlp, scaler)
    print(f"{'mlp':14s} RMSE={metrics['RMSE']:.4f}  R2={metrics['R2']:.4f}  "
          f"nRMSE%={metrics['nRMSE_%']:.2f}  train={train_time:.1f}s")

    comparison = pd.DataFrame(rows).set_index("modele").sort_values("RMSE")
    print("\n--- Classement sur holdout (RMSE) ---")
    print(comparison[["RMSE", "R2", "nRMSE_%"]].round(4).to_string())

    preds = {name: model.predict(X_test) if name != "mlp"
             else model[0].predict(model[1].transform(X_test))
             for name, model in fitted.items()}
    return fitted, comparison, preds, (X_test, y_test)


# --------------------------------------------------------------------------- #
# 8. ENSEMBLE
# --------------------------------------------------------------------------- #


def build_ensemble(comparison: pd.DataFrame, hpo_results: dict,
                   preds: dict, y_test) -> tuple[dict, dict, float]:
    """Ensemble pondéré (1/RMSE_CV) des 3 meilleurs modèles holdout."""
    top_n = 3
    top_models = comparison.index[:top_n].tolist()

    weights = {m: 1.0 / hpo_results[m]["best_cv_rmse"] for m in top_models}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}

    ensemble_pred = sum(weights[m] * preds[m] for m in top_models)
    ensemble_metrics = compute_metrics(y_test, ensemble_pred)

    best_rmse = comparison.loc[comparison["RMSE"].idxmin(), "RMSE"]
    gain_pct = (best_rmse - ensemble_metrics["RMSE"]) / best_rmse * 100

    print(f"\n--- Ensemble {top_models} (poids { {k: round(v, 3) for k, v in weights.items()} }) ---")
    print(f"RMSE meilleur seul : {best_rmse:.4f} | Ensemble : {ensemble_metrics['RMSE']:.4f} "
          f"| Gain : {gain_pct:+.2f}%")

    decision = f"ensemble({'+'.join(top_models)})" if gain_pct > 2.0 else comparison["RMSE"].idxmin()
    print(f"Modèle final retenu : {decision}")
    return weights, top_models, gain_pct, decision, ensemble_metrics


# --------------------------------------------------------------------------- #
# 9. EXPLICABILITE (SHAP, corrigé pour HistGB)
# --------------------------------------------------------------------------- #


def explain_model(fitted: dict, best_name: str, X_test: pd.DataFrame, sample: int = 3000):
    """SHAP sur le meilleur modèle unique. HistGB n'a pas feature_importances_ :
    l'importance 'gain' native est remplacée par l'importance SHAP seule."""
    import shap

    explain_model = fitted[best_name]
    if isinstance(explain_model, tuple):
        print("SHAP non supporté pour MLP (baseline) - analyse sautée.")
        return

    shap_sample = X_test.sample(min(sample, len(X_test)), random_state=RANDOM_SEED)
    explainer = shap.TreeExplainer(explain_model)
    shap_values = explainer.shap_values(shap_sample)

    mean_abs_shap = (
        pd.Series(np.abs(shap_values).mean(axis=0), index=shap_sample.columns)
        .sort_values(ascending=False)
    )
    print("\n--- Top features SHAP ---")
    print(mean_abs_shap.head(10).round(4).to_string())

    # Barplot top 15 (sans dépendre de feature_importances_)
    fig, ax = plt.subplots(figsize=(8, 7))
    mean_abs_shap.head(15).plot.barh(ax=ax, color="#2a78d6")
    ax.invert_yaxis()
    ax.set_xlabel("|SHAP| moyen")
    ax.set_title(f"Importance SHAP - {best_name}")
    fig.tight_layout()
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES_DIR / "03_shap_importance.png", dpi=110, bbox_inches="tight")
    plt.show()


# --------------------------------------------------------------------------- #
# 10. ANALYSE DES RESIDUS / ERREURS PAR SITE
# --------------------------------------------------------------------------- #


def analyze_errors(df: pd.DataFrame, best_name: str, fitted: dict,
                   preds: dict, X_test, y_test, comparison: pd.DataFrame,
                   X: pd.DataFrame, y: np.ndarray, hpo_results: dict):
    """Résidus + métriques par site sur le holdout."""
    train_idx, test_idx = final_split_indices(df)
    pred_best = preds[best_name]
    test_meta = df.loc[test_idx, ["timestamp", "site_id", "hour", "month", "clearsky_index"]].copy()
    test_meta["y_true"] = y_test
    test_meta["y_pred"] = pred_best
    test_meta["residual"] = pred_best - y_test

    by_site = test_meta.groupby("site_id").apply(
        lambda g: pd.Series(compute_metrics(g["y_true"], g["y_pred"]))
    )
    print("\n--- Erreur par site (holdout) ---")
    print(by_site[["RMSE", "R2", "nRMSE_%"]].round(4).to_string())

    # Sur-apprentissage : train vs CV vs test
    train_metrics = compute_metrics(y[train_idx],
                                    _predict_refit(best_name, fitted, X.iloc[train_idx]))
    overfit = pd.DataFrame({
        "RMSE": [train_metrics["RMSE"], hpo_results[best_name]["best_cv_rmse"],
                 comparison.loc[best_name, "RMSE"]],
        "R2": [train_metrics["R2"], np.nan, comparison.loc[best_name, "R2"]],
    }, index=["train (refit)", "CV (5 folds)", "test holdout"])
    print("\n--- Sur-apprentissage ---")
    print(overfit.round(4).to_string())

    # Classement CV vs holdout
    rank_cmp = pd.DataFrame({
        "CV_RMSE": {m: hpo_results[m]["best_cv_rmse"] for m in hpo_results},
        "Holdout_RMSE": comparison["RMSE"],
    })
    rank_cmp["rang_CV"] = rank_cmp["CV_RMSE"].rank().astype(int)
    rank_cmp["rang_holdout"] = rank_cmp["Holdout_RMSE"].rank().astype(int)
    print("\n--- Stabilité du classement CV vs holdout ---")
    print(rank_cmp.sort_values("rang_holdout").to_string())
    return by_site, overfit, rank_cmp


def _predict_refit(best_name, fitted, X):
    if best_name == "mlp":
        model, scaler = fitted["mlp"]
        return model.predict(scaler.transform(X))
    return fitted[best_name].predict(X)


# --------------------------------------------------------------------------- #
# 11. EXPORT DU MODELE FINAL
# --------------------------------------------------------------------------- #


def export_bundle(df: pd.DataFrame, X, y, hpo_results: dict, decision: str,
                  top_models: list, weights: dict,
                  ensemble_metrics: dict, comparison: pd.DataFrame) -> dict:
    """Refit sur toutes les données + sauvegarde du bundle de déploiement."""
    import joblib
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler

    def fit_final_member(name: str, best_params: dict):
        if name == "mlp":
            scaler = StandardScaler().fit(X)
            arch = [(64,), (128,), (64, 32), (128, 64), (128, 64, 32)][best_params["arch_idx"]]
            model = MLPRegressor(
                hidden_layer_sizes=arch, alpha=best_params["alpha"],
                learning_rate_init=best_params["learning_rate_init"],
                early_stopping=True, n_iter_no_change=15, max_iter=300,
                validation_fraction=0.15, random_state=RANDOM_SEED,
            )
            model.fit(scaler.transform(X), y)
            return model, scaler
        if name in ("xgboost", "lightgbm", "catboost"):
            params = dict(best_params)
            params.update(n_estimators=300, random_state=RANDOM_SEED)
            if name == "xgboost":
                params.update(n_jobs=1, tree_method="hist")
            elif name == "lightgbm":
                params.update(n_jobs=1, verbosity=-1)
            else:
                params.update(iterations=300, thread_count=1, verbose=False,
                              bootstrap_type="Bernoulli", random_seed=RANDOM_SEED)
            model = build_model(name, params)
            model.fit(X, y)
            return model, None
        model = build_model(name, best_params)
        model.fit(X, y)
        return model, None

    if decision == "mlp":  # modèle unique : liste à 1 membre
        member_names, member_weights = ["mlp"], [1.0]
    elif decision.startswith("ensemble"):
        member_names, member_weights = top_models, [weights[m] for m in top_models]
    else:
        member_names, member_weights = [decision], [1.0]

    members = [
        {"name": name, "model": model, "scaler": scaler}
        for name in member_names
        for model, scaler in [fit_final_member(name, hpo_results[name]["best_params"])]
    ]

    bundle = {
        "final_choice": decision,
        "members": members,
        "weights": member_weights,
        "feature_columns": list(X.columns),
        "site_coords": SITE_COORDS,
        "timezone": TZ,
        "installed_capacity_mw": INSTALLED_CAPACITY_MW,
        "mape_threshold_mw": MAPE_THRESHOLD_MW,
        "holdout_test_metrics": (
            comparison.loc[decision].to_dict() if decision != "mlp" and not decision.startswith("ensemble")
            else dict(ensemble_metrics)
        ),
        "training_data_range": [str(df["timestamp"].min()), str(df["timestamp"].max())],
    }

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, MODELS_DIR / "final_model_bundle.joblib")
    print(f"\nModèle final exporté ({decision}) -> {MODELS_DIR / 'final_model_bundle.joblib'}")
    print(f"Membres: {member_names} | Poids: {[round(w, 3) for w in member_weights]}")
    print(f"Features: {len(bundle['feature_columns'])}")
    return bundle


def predict_production(weather_forecast_df: pd.DataFrame, bundle: dict) -> np.ndarray:
    """Prévision sur de nouvelles données météo (aucun historique de production requis)."""
    feat = add_calendar_features(weather_forecast_df.copy())
    feat = add_solar_geometry(feat)
    feat = add_physical_features(feat)
    X_new = build_design_matrix(feat, feature_cols=FINAL_FEATURE_COLS)
    X_new = X_new.reindex(columns=bundle["feature_columns"], fill_value=0.0)

    pred = np.zeros(len(X_new))
    for member, weight in zip(bundle["members"], bundle["weights"]):
        X_in = member["scaler"].transform(X_new) if member["scaler"] is not None else X_new
        pred += weight * member["model"].predict(X_in)

    # Garde-fou physique (indépendant du modèle ML) : aucune production
    # possible soleil couché, cohérent avec la correction 2 du prétraitement
    # (production_mw forcée à 0 quand is_day == 0). Sans ce clip, le modèle
    # peut halluciner une production nocturne non nulle (observé sur feriana_csfc
    # avant correction : ~3.3 MW prédits à une heure de nuit du holdout).
    is_night = (feat["is_day"].fillna(0) == 0) | (feat["solar_elevation"] <= 0)
    pred = np.where(is_night.values, 0.0, pred)
    pred = np.clip(pred, 0.0, bundle.get("installed_capacity_mw", INSTALLED_CAPACITY_MW))
    return pred


# --------------------------------------------------------------------------- #
# 12. ORCHESTRATION
# --------------------------------------------------------------------------- #


def main(skip_hpo: bool = False, quick: bool = False) -> None:
    t_start = time.time()
    warnings.filterwarnings("ignore")
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    for directory in (FINAL_DIR, MODELS_DIR, FIGURES_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("STEG HelioCast AI - Pipeline de modélisation")
    print("=" * 60)

    # 1. Prétraitement
    ready = build_modeling_ready_dataset()

    # 2. Features
    df = build_feature_dataset(ready)

    # 3. Matrice de design + cible
    X = build_design_matrix(df)
    y = df["production_mw"].values
    print(f"\nDesign matrix : {X.shape}")

    all_folds = list(cv_split_indices(df))
    print(f"Train final (< {HOLDOUT_START}) : {len(final_split_indices(df)[0])} lignes")
    print(f"Test holdout (>= {HOLDOUT_START}) : {len(final_split_indices(df)[1])} lignes")

    # 4. Optuna
    if skip_hpo:
        hpo_results = {
            name: json.load(open(MODELS_DIR / f"hpo_{name}.json"))
            for name in MODEL_SPECS
            if (MODELS_DIR / f"hpo_{name}.json").exists()
        }
        missing = [m for m in MODEL_SPECS if m not in hpo_results]
        if missing:
            raise FileNotFoundError(f"Cache Optuna manquant pour : {missing}. Lancement sans --skip-hpo requis.")
        print(f"HPO chargé depuis cache : {list(hpo_results)}")
    else:
        hpo_results = run_hpo(X, y, all_folds, quick=quick)

    # 5. Comparaison sur holdout
    fitted, comparison, preds, (X_test, y_test) = compare_models_on_holdout(df, X, y, hpo_results)

    # 6. Ensemble
    weights, top_models, gain_pct, decision, ensemble_metrics = build_ensemble(
        comparison, hpo_results, preds, y_test
    )

    # 7. Explicabilité (meilleur modèle unique)
    best_name = comparison["RMSE"].idxmin()
    explain_model(fitted, best_name, X_test)

    # 8. Analyse des erreurs
    analyze_errors(df, best_name, fitted, preds, X_test, y_test, comparison, X, y, hpo_results)

    # 9. Export
    bundle = export_bundle(df, X, y, hpo_results, decision, top_models,
                           weights, ensemble_metrics, comparison)

    # 10. Démo
    demo_idx = final_split_indices(df)[1][:48]
    demo = df.iloc[demo_idx]
    demo_pred = predict_production(demo, bundle)
    print("\n--- Démo 48h holdout ---")
    print(pd.DataFrame({
        "timestamp": demo["timestamp"].values, "site_id": demo["site_id"].values,
        "production_reelle_mw": demo["production_mw"].values,
        "production_predite_mw": np.round(demo_pred, 3),
    }).head(10).to_string(index=False))

    print(f"\nPipeline terminé en {time.time() - t_start:.0f}s.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de modélisation PV STEG")
    parser.add_argument("--skip-hpo", action="store_true",
                        help="Réutilise le cache Optuna existant (pas de nouvelle recherche)")
    parser.add_argument("--quick", action="store_true",
                        help="Mini-pipeline : 2 essais Optuna max par modèle (validation rapide)")
    args = parser.parse_args()
    main(skip_hpo=args.skip_hpo, quick=args.quick)
