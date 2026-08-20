# STEG HelioCast AI — Deploiement (job quotidien + API de lecture)

Batch et API : le job ecrit dans MySQL `heliocast.forecasts`, l'API ne fait que lire.
**Aucun retrain** : le bundle v14 (`models_final_14/final_model_bundle.joblib`, lightgbm) est
charge tel quel via `modeling/inference.py` (source unique des features : `scripts/modeling_v14.py`).

## Architecture

```
[Open-Meteo] --(job 00:05 / a la demande)--> forecast_job.py --> MySQL heliocast.forecasts
                                                                    |
                                                                    v
[Tableau de bord] <-- FastAPI <-- api.py <-- MySQL
                     /health, /model/meta, /forecasts/latest, /forecasts/refresh
```

## 1. Structure

```
deploy/
├── app/
│   ├── __init__.py
│   ├── config.py         # env vars (DB_*, BUNDLE_PATH, FORECAST_DAYS...)
│   ├── db.py             # MySQL : schema, upsert, lecture dernier lot
│   ├── forecast_job.py   # job quotidien : meteo -> inference -> insert
│   └── api.py            # FastAPI + dashboard statique (deploy/app/static)
├── requirements.txt
├── .env.example          # copier en .env et remplir
├── Dockerfile            # image api (python:3.12-slim + libgomp1 pour LightGBM)
├── docker-compose.yml    # mysql (3307) + api (8000) ; job au demarrage de l'api
├── crontab               # 00:00 UTC chaque jour (Linux hors conteneur)
├── schedule_windows.ps1  # alternative Windows (Planificateur de taches)
└── README.md
```

## 2. Lancement en local (Windows)

```powershell
# 1) dependances
pip install -r deploy\requirements.txt

# 2) MySQL pret (XAMPP ou : docker run -e MYSQL_ROOT_PASSWORD=root_changer -e MYSQL_DATABASE=heliocast -p 3306:3306 mysql:8.0)
# 3) config
Copy-Item deploy\.env.example deploy\.env   # editer DB_PASSWORD

# 4) test du job (ecrit 1008 lignes = 6 sites x 24h x 7j)
python -m deploy.app.forecast_job --days 7

# 5) API
uvicorn deploy.app.api:app --port 8000
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/model/meta
curl http://127.0.0.1:8000/forecasts/latest
```

## 3. Docker

```bash
# depuis la racine du projet (ou double-clic sur demarrer_docker.bat)
docker compose -f deploy/docker-compose.yml up -d --build
# ouvrir http://localhost:8000
```

- `mysql` : MySQL 8.0, conteneur `heliocast-mysql`, port hote **3307** (evite tout conflit avec un XAMPP local sur 3306), volume `mysql_data` persistant.
- `api` : conteneur `heliocast-api`, port **8000**. Pas de conteneur `batch` : le job tourne au demarrage du conteneur, puis FastAPI prend le relais.

Verification : `docker compose -f deploy/docker-compose.yml logs -f api`

```bash
# apres un git pull, reconstruire l'image (le dashboard + le job y sont copies)
docker compose -f deploy/docker-compose.yml up -d --build api
# rejouer le job a la main
docker exec heliocast-api python -m deploy.app.forecast_job
# arret
docker compose -f deploy/docker-compose.yml down
```

### Notes Docker (validees sur PC serveur, juin 2026)

- **EOL Windows** : le `ENTRYPOINT` shell du Dockerfile est desactive (`entrypoint: []`) ;
  la commande est definie inline dans le compose (`sh -c`) — le clipboard git Windows
  (CRLF) ne peut plus casser le demarrage. Garder `.gitattributes` (`*.sh text eol=lf`).
- **libgomp1 obligatoire** : sans lui, LightGBM plante au chargement dans l'image
  python:3.12-slim (`OSError: libgomp.so.1`). Present dans le Dockerfile.
- **Attente de MySQL** en python/pymysql (le client `mysqladmin` de Debian est
  incompatible avec l'auth `caching_sha2_password` de MySQL 8).
- **Premier demarrage lent** (machine modeste) : init InnoDB ~4,5 min (jusqu'a ~2 h au
  tout premier `up`) ; le compose attend `service_healthy` avant de lancer l'api.

## 4. Job quotidien (detail)

1. `ensure_schema()` : cree la base/table si absentes.
2. `ForecastPipeline(bundle)` : charge le bundle v14 (aucun entrainement).
3. `forecast_all_sites(forecast_days=7)` : Open-Meteo → features → prediction
   (nuit forcee a 0, clip a la capacite du site via `capacity_map_mw`).
4. Controle volume : exactement `6 sites x 24 h x 7 j = 1008` lignes, sinon **abandon**.
5. Upsert MySQL par `(site_id, timestamp, generated_at)` — un second passage
   apres echec ecrase la meme vague (idempotent). Avec `replace=True`, les anciennes
   vagues sont supprimees apres insertion de la nouvelle.
6. Logs : `logs/deploy.log` (rotation 5 Mo x 3) + stdout.

Codes de sortie : `0` ok, `1` MySQL, `2` bundle, `3` meteo/inference, `4` volume, `5` insert.

## 5. API

| Endpoint | Reponse |
|----------|---------|
| `GET /health` | etat service + ping MySQL |
| `GET /model/meta` | `final_choice`, version, 31 features, `data_hash`, `capacity_map_mw`, `holdout_test_metrics` (du bundle) |
| `GET /forecasts/latest` | `generated_at`, `forecast_days`, `sites`, `count`, `data[]` (`site_id`, `timestamp`, `prediction_mw`) |
| `POST /forecasts/refresh` | nouvelle vague a la demande (`replace=True`), bouton « Nouvelle prevision » du dashboard |

Le dashboard statique (build React) est monte sur `/` : toute autre route sert
l'application, les routes `/health`, `/model/meta`, `/forecasts/*` restent prioritaires.

## 6. Notes

- Le modele v14 = **lightgbm** (meilleure CV walk-forward 0.8151), les metriques
  exactes du holdout sont lues depuis le bundle, jamais codees en dur.
- En production : `DB_PASSWORD` via secret manager, jamais en dur.
- Dashboard : apres chaque modification de `dashboard/src/`, executer
  `npm run build` dans `dashboard/` et recopier `dashboard/dist/` vers `deploy/app/static/`
  (ou recompiler l'image Docker, qui copie `deploy/` au build).