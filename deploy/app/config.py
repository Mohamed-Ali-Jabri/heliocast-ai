"""
STEG HelioCast AI - config du deploiement (batch + API).
Lit tout depuis les variables d'environnement (.env supporte).
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# deploy/app/config.py -> racine du projet (parents[2])
APP_DIR = Path(__file__).resolve().parent
DEPLOY_DIR = APP_DIR.parent
PROJECT_ROOT = DEPLOY_DIR.parent

if load_dotenv is not None:
    load_dotenv(DEPLOY_DIR / ".env")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "heliocast")
DB_USER = os.getenv("DB_USER", "heliocast")
DB_PASSWORD = os.getenv("DB_PASSWORD", "changer_moi")

BUNDLE_PATH = Path(
    os.getenv("BUNDLE_PATH", str(PROJECT_ROOT / "models_final_14" / "final_model_bundle.joblib"))
)
FORECAST_DAYS = int(os.getenv("FORECAST_DAYS", "7"))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "deploy.log"

MODEL_VERSION = os.getenv("MODEL_VERSION", "v14")
API_PORT = int(os.getenv("API_PORT", "8000"))
