"""
STEG HelioCast AI - API (FastAPI).

Endpoints :
    GET     /health            -> etat du service + connexion MySQL
    GET     /model/meta        -> metadonnees du modele (bundle v14)
    GET     /forecasts/latest  -> dernier lot de previsions en base
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import joblib
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from . import db as helio_db
from . import forecast_job

# Import de l'interface d'inference par chemin explicite (importlib) :
# resolu par le linter ET independant du repertoire de travail.
_INFERENCE_PATH = config.PROJECT_ROOT / "modeling" / "inference.py"
_spec = importlib.util.spec_from_file_location("heliocast_inference", _INFERENCE_PATH)
_inference = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_inference)

SITE_COORDS = _inference.SITE_COORDS

log = logging.getLogger("heliocast.api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="STEG HelioCast AI - API de previsions PV",
    version=config.MODEL_VERSION,
    description=(
        "Lecture des previsions de production photovoltaique generees "
        "chaque nuit par le job quotidien (6 sites tunisiens)."
    ),
)

_bundle_meta: dict | None = None


def _load_bundle_meta() -> dict:
    global _bundle_meta
    if _bundle_meta is None:
        bundle = joblib.load(config.BUNDLE_PATH)
        _bundle_meta = {
            "model": bundle.get("final_choice", "unknown"),
            "version": config.MODEL_VERSION,
            "features": len(bundle.get("feature_columns", [])),
            "data_hash": bundle.get("data_hash"),
            "capacity_map_mw": bundle.get("capacity_map_mw"),
            "holdout_test_metrics": bundle.get("holdout_test_metrics"),
        }
    return _bundle_meta


@app.get("/health")
def health():
    try:
        meta = _load_bundle_meta()
        db_ok = helio_db.ping()
        return {
            "status": "ok" if db_ok else "degraded",
            "model_version": meta["version"],
            "model": meta["model"],
            "database": "ok" if db_ok else "unreachable",
            "sites": len(SITE_COORDS),
        }
    except Exception as err:
        log.exception("Health check KO")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(err)},
        )


@app.get("/model/meta")
def model_meta():
    try:
        return _load_bundle_meta()
    except Exception as err:
        log.exception("model/meta KO")
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(err)})


@app.get("/forecasts/latest")
def forecasts_latest():
    try:
        batch = helio_db.latest_forecast_batch()
    except Exception as err:
        log.exception("MySQL KO")
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "detail": "Base de donnees MySQL injoignable : " + str(err),
            },
        )

    if batch is None:
        return JSONResponse(
            status_code=404,
            content={
                "status": "error",
                "detail": "Aucune prevision en base de donnees",
            },
        )
    rows = batch["rows"]
    generated = batch["generated_at"]
    if not isinstance(generated, str):
        generated = generated.strftime("%Y-%m-%d %H:%M:%S")
    data = [
        {
            "site_id": r["site_id"],
            "timestamp": r["timestamp"].strftime("%Y-%m-%d %H:%M"),
            "prediction_mw": float(r["prediction_mw"]),
        }
        for r in rows
    ]
    return {
        "generated_at": generated,
        "forecast_days": len({r["timestamp"].date() for r in rows}),
        "sites": sorted({r["site_id"] for r in rows}),
        "count": len(data),
        "data": data,
    }


@app.post("/forecasts/refresh")
def forecasts_refresh():
    """Lance une NOUVELLE prevision : insere le nouveau lot puis
    supprime TOUTES les anciennes previsions (replace=True)."""
    try:
        code = forecast_job.run_forecast_job(replace=True)
    except Exception as err:
        log.exception("refresh KO")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": "Erreur pendant la generation : " + str(err)},
        )
    if code != 0:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": f"Le job de prevision a echoue (code {code}). Aucune donnee supprimee."},
        )
    return {"status": "ok", "message": "Nouvelles previsions generees, anciennes supprimees."}


# Dashboard HTML (dernier : ne masque pas les routes API)
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="dashboard")