"""
STEG HelioCast AI - job quotidien 00:00.

    Open-Meteo -> features (scripts/modeling_v14.py) -> bundle v14
    -> 6 sites x 24h x FORECAST_DAYS -> MySQL heliocast.forecasts

Aucun retrain : le bundle est charge tel quel via modeling/inference.py.
"""
from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from . import config
from . import db as helio_db

# Import de l'interface d'inference par chemin explicite (importlib) :
# resolu par le linter ET independant du repertoire de travail.
_INFERENCE_PATH = config.PROJECT_ROOT / "modeling" / "inference.py"
_spec = importlib.util.spec_from_file_location("heliocast_inference", _INFERENCE_PATH)
_inference = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_inference)

ForecastPipeline = _inference.ForecastPipeline
SITE_COORDS = _inference.SITE_COORDS


def setup_logging() -> logging.Logger:
    log = logging.getLogger("heliocast.job")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(sh)
    fh = RotatingFileHandler(config.LOG_FILE, maxBytes=5_000_000, backupCount=3)
    fh.setFormatter(fmt)
    log.addHandler(fh)
    return log


def run_forecast_job(days: int | None = None, replace: bool = False) -> int:
    log = setup_logging()
    days = days or config.FORECAST_DAYS
    started = datetime.now(timezone.utc)
    log.info("=== Debut du job quotidien (days=%d, replace=%s) ===", days, replace)

    try:
        helio_db.ensure_schema()
    except Exception:
        log.exception("Echec init schema MySQL — verifier DB_HOST/DB_NAME/DB_USER/DB_PASSWORD")
        return 1

    try:
        pipeline = ForecastPipeline(str(config.BUNDLE_PATH))
    except FileNotFoundError as err:
        log.error("Bundle introuvable : %s", err)
        return 2

    try:
        forecasts = pipeline.forecast_all_sites(forecast_days=days)
    except Exception:
        log.exception("Echec recuperation meteo / inference (Open-Meteo injoignable ?)")
        return 3

    expected = len(SITE_COORDS) * 24 * days
    if len(forecasts) != expected:
        log.error(
            "Volume inattendu : %d lignes attendues=%d — abandon (aucun insert)",
            len(forecasts), expected,
        )
        return 4

    try:
        if replace:
            generated_at = datetime.now().replace(microsecond=0)
            helio_db.upsert_forecasts(forecasts, generated_at=generated_at)
            helio_db.purge_forecasts(keep_generated_at=generated_at)
        else:
            helio_db.upsert_forecasts(forecasts)
    except Exception:
        log.exception("Echec insert MySQL")
        return 5

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    summary = (
        forecasts.groupby("site_id")["production_predite_mw"]
        .agg(["mean", "max"])
        .round(3)
    )
    log.info("Job termine en %.1fs : %d previsions (6 sites x %d j)", duration, len(forecasts), days)
    log.info("Resume par site :\n%s", summary.to_string())
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Job quotidien de prevision PV (STEG HelioCast)")
    parser.add_argument("--days", type=int, default=None, help="Horizon en jours (defaut: env FORECAST_DAYS=7)")
    parser.add_argument("--replace", action="store_true", help="Supprime les anciennes previsions apres insertion")
    args = parser.parse_args()
    sys.exit(run_forecast_job(days=args.days, replace=args.replace))


if __name__ == "__main__":
    main()
