"""
STEG HelioCast AI - module d'inference pour le deploiement - MODELE V13.
=========================================================================

Interface de prevision dediee au modele V13 (models_final_13) :
meme job que inference.py mais charge le bundle V13 par defaut et
ecrit les previsions dans resultat13.csv.

    - Bundle : models_final_13/final_model_bundle.joblib
      (modele retenu : extratrees, CV RMSE 0.8225)
    - Features : identiques V13/V14 (31 colonnes, verifiees) -> import
      depuis modeling_v14.py (source unique de verite).
    - Capacite par site : capacity_map_mw du bundle (10 MW tous sites).

Usage programmatique :
    from inference_modelv13 import ForecastPipelineV13
    pipeline = ForecastPipelineV13()
    forecasts = pipeline.forecast_all_sites(forecast_days=7)

Usage en ligne de commande :
    python modeling/inference_modelv13.py --output resultat13.csv
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import joblib

# ---------------------------------------------------------------------------
# Import direct du pipeline de features d'entrainement (source unique de verite)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from modeling_v14 import (  
    add_calendar_features,
    add_solar_geometry,
    add_physical_features,
    build_design_matrix,
    build_capacity_map,
    FINAL_FEATURE_COLS,
    SITE_COORDS,
    TZ,
)

# ---------------------------------------------------------------------------
# Configuration specifique au modele V13
# ---------------------------------------------------------------------------
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

DEFAULT_BUNDLE = str(PROJECT_ROOT / "models_final_13" / "final_model_bundle.joblib")
DEFAULT_OUTPUT = "resultat13.csv"

HOURLY_VARIABLES = [
    "shortwave_radiation", "direct_normal_irradiance", "direct_radiation",
    "diffuse_radiation", "temperature_2m", "wind_speed_10m", "cloud_cover",
    "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "relative_humidity_2m", "visibility", "precipitation", "is_day",
]


# ---------------------------------------------------------------------------
# Recuperation des previsions meteo temps reel
# ---------------------------------------------------------------------------
def fetch_weather_forecast(site_id: str, forecast_days: int = 7,
                            timeout: int = 60, retries: int = 3) -> pd.DataFrame:
    """Recupere la prevision meteo horaire J -> J+forecast_days-1 pour un site,
    depuis l'API Forecast Open-Meteo (memes variables/format que l'API Historical
    Forecast utilisee pour l'entrainement)."""
    if site_id not in SITE_COORDS:
        raise ValueError(f"site_id inconnu : {site_id!r}. Sites disponibles : {list(SITE_COORDS)}")

    lat, lon, _ = SITE_COORDS[site_id]
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(HOURLY_VARIABLES),
        "models": "best_match",
        "forecast_days": forecast_days,
        "timezone": TZ,
    }
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(OPEN_METEO_FORECAST_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()["hourly"]
            df = pd.DataFrame(payload)
            df["timestamp"] = pd.to_datetime(df["time"])
            df["site_id"] = site_id
            return df.drop(columns=["time"])
        except (requests.RequestException, KeyError) as err:
            last_err = err
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Echec recuperation meteo pour {site_id} apres {retries} essais: {last_err}")


# ---------------------------------------------------------------------------
# Pipeline de prevision
# ---------------------------------------------------------------------------
class ForecastPipelineV13:
    def __init__(self, bundle_path: str | None = None):
        bundle_path = Path(bundle_path) if bundle_path else Path(DEFAULT_BUNDLE)
        if not bundle_path.exists():
            raise FileNotFoundError(
                f"Bundle V13 introuvable : {bundle_path}. "
                f"Verifiez que models_final_13/final_model_bundle.joblib existe."
            )
        self.bundle = joblib.load(bundle_path)

        # Capacite par site : capacity_map_mw du bundle (fallback config).
        self.capacity_map_mw = self.bundle.get("capacity_map_mw")
        if self.capacity_map_mw is None:
            single_cap = self.bundle.get("installed_capacity_mw")
            if single_cap is not None:
                self.capacity_map_mw = {
                    site: float(single_cap)
                    for site in SITE_COORDS
                }
            else:
                self.capacity_map_mw = build_capacity_map()

    def predict(self, weather_df: pd.DataFrame) -> pd.DataFrame:

        required_cols = {"timestamp", "site_id", *HOURLY_VARIABLES}
        missing = required_cols - set(weather_df.columns)
        if missing:
            raise ValueError(f"Colonnes manquantes dans weather_df : {sorted(missing)}")

        feat = add_calendar_features(weather_df.copy())
        feat = add_solar_geometry(feat)          # astronomie pure, ordre d'entree preserve
        feat = add_physical_features(feat)

        X_new = build_design_matrix(feat, feature_cols=FINAL_FEATURE_COLS)
        X_new = X_new.reindex(columns=self.bundle["feature_columns"], fill_value=0.0)

        pred = np.zeros(len(X_new))
        for member, weight in zip(self.bundle["members"], self.bundle["weights"]):
            X_in = member["scaler"].transform(X_new) if member["scaler"] is not None else X_new
            pred += weight * member["model"].predict(X_in)

        # Garde-fou physique : aucune production possible soleil couche,
        # bornage a la capacite installee du site.
        is_night = (feat["is_day"].fillna(0) == 0) | (feat["solar_elevation"] <= 0)
        pred = np.where(is_night.values, 0.0, pred)
        pred = np.maximum(pred, 0.0)

        capacities = (
            feat["site_id"]
            .map(self.capacity_map_mw)
            .to_numpy()
        )
        valid_capacity = ~pd.isna(capacities)
        if valid_capacity.any():
            pred[valid_capacity] = np.minimum(
                pred[valid_capacity],
                capacities[valid_capacity],
            )

        result = feat[["timestamp", "site_id"]].copy()
        result["production_predite_mw"] = np.round(pred, 4)
        return result.reset_index(drop=True)

    def forecast_all_sites(self, forecast_days: int = 7) -> pd.DataFrame:
        """Prevision pour tous les sites connus (config/sites.yaml / SITE_COORDS)."""
        all_preds = []
        for site_id in SITE_COORDS:
            weather = fetch_weather_forecast(site_id, forecast_days=forecast_days)
            all_preds.append(self.predict(weather))
        return pd.concat(all_preds, ignore_index=True).sort_values(["timestamp", "site_id"]).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(
        description="Prevision de production PV - STEG HelioCast AI (modele V13)"
    )
    parser.add_argument("--bundle", default=DEFAULT_BUNDLE,
                         help="Chemin vers final_model_bundle.joblib "
                              "(defaut : models_final_13)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                         help=f"Fichier CSV de sortie (defaut : {DEFAULT_OUTPUT})")
    parser.add_argument("--days", type=int, default=7, help="Horizon de prevision (jours, max 16)")
    args = parser.parse_args()

    try:
        pipeline = ForecastPipelineV13(args.bundle)
    except FileNotFoundError as err:
        print(f"ERREUR: {err}", file=sys.stderr)
        sys.exit(1)

    forecasts = pipeline.forecast_all_sites(forecast_days=args.days)
    forecasts.to_csv(args.output, index=False)

    print(f"{len(forecasts)} previsions V13 ({len(SITE_COORDS)} sites x {args.days}j) -> {args.output}")
    print(forecasts.groupby("site_id")["production_predite_mw"].agg(["mean", "max"]).round(3))


if __name__ == "__main__":
    main()