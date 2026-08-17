# STEG HelioCast AI — Deploiement (job quotidien + API de lecture)

Batch et API **separement** : le job ecrit dans MySQL `heliocast.forecasts`, l'API ne fait que lire.
**Aucun retrain** : le bundle v14 (`models_final_14/final_model_bundle.joblib`, lightgbm) est
charge tel quel via `modeling/inference.py` (source unique des features : `scripts/modeling_v14.py`).

## Architecture

```
[Open-Meteo] --(00:00 UTC, cron)--> deploy/app/forecast_job.py --> MySQL heliocast.forecasts
                                                                          |
                                                                          v
[Tableau de bord] <-- FastAPI <-- deploy/app/api.py <-- MySQL
                     /health, /model/meta, /forecasts/latest
```

## 1. Structure

```
deploy/
├── app/
│   ├── __init__.py
│   ├── config.py         # env vars (DB_*, BUNDLE_PATH, FORECAST_DAYS...)
│   ├── db.py             # MySQL : schema, upsert, lecture dernier lot
│   ├── forecast_job.py   # job quotidien : meteo -> inference -> insert
│   └── api.py            # FastAPI : /health /model/meta /forecasts/latest
├── requirements.txt
├── .env.example          # copier en .env et remplir
├── Dockerfile            # image job+API (cron inclus)
├── docker-compose.yml    # db + batch + api
├── crontab               # 00:00 UTC chaque jour
└── schedule_windows.ps1  # alternative Windows (Planificateur de taches)
```

## 2. Lancement en local (Windows)

```powershell
# 1) dependances
pip install -r deploy\requirements.txt

# 2) MySQL pret (ou MySQL 8 via Docker Desktop : docker run -e MYSQL_ROOT_PASSWORD=root_changer -e MYSQL_DATABASE=heliocast -p 3306:3306 mysql:8.0)
# 3) config
Copy-Item deploy\.env.example deploy\.env   # editer DB_PASSWORD

# 4) test du job (ecrit ~1008 lignes = 6 sites x 24h x 7j)
python -m deploy.app.forecast_job --days 7

# 5) API
uvicorn deploy.app.api:app --port 8000
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/model/meta
curl http://127.0.0.1:8000/forecasts/latest
```

## 3. Docker

```bash
docker compose -f deploy/docker-compose.yml up --build -d
```

- `db` : MySQL 8 (`heliocast` creee au 1er demarrage)
- `batch` : lance `cron -f` → job chaque nuit a 00:00 UTC
- `api` : uvicorn sur le port 8000

Verification : `docker compose -f deploy/docker-compose.yml logs -f batch api`

## 4. Job quotidien (detail)

1. `ensure_schema()` : cree la base/table si absentes.
2. `ForecastPipeline(bundle)` : charge le bundle v14 (aucun entrainement).
3. `forecast_all_sites(forecast_days=7)` : Open-Meteo → features → prediction
   (nuit forcee a 0, clip a la capacite du site via `capacity_map_mw`).
4. Controle volume : exactement `6 sites x 24 h x 7 j = 1008` lignes, sinon **abandon**.
5. Upsert MySQL par `(site_id, timestamp, generated_at)` — un second passage
   apres echec ecrase la meme vague (idempotent).
6. Logs : `logs/deploy.log` (rotation 5 Mo x 3) + stdout.

Codes de sortie : `0` ok, `1` MySQL, `2` bundle, `3` meteo/inference, `4` volume, `5` insert.

## 5. API

| Endpoint             | Reponse |
|----------------------|---------|
| `GET /health`        | etat service + ping MySQL |
| `GET /model/meta`    | `final_choice`, version, 31 features, `data_hash`, `capacity_map_mw`, `holdout_test_metrics` (du bundle) |
| `GET /forecasts/latest` | `generated_at`, `forecast_days`, `sites`, `count`, `data[]` (`site_id`, `timestamp`, `prediction_mw`) |

## 6. Notes

- Le modele v14 = **lightgbm** (meilleure CV), holdout RMSE 0.9124 / R² 0.9027
  (extratrees) — les valeurs exactes sont lues depuis le bundle, pas codées en dur.
- Tuner le cron si besoin d'une autre heure (ex. `0 3 * * *` pour 03:00 UTC).
- En production : `DB_PASSWORD` via secret manager, jamais en dur.
