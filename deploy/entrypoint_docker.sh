#!/bin/sh
set -e

echo "[1/3] Attente de MySQL ($DB_HOST:$DB_PORT)..."
until mysqladmin ping -h "$DB_HOST" -P "$DB_PORT" -u root -p"$MYSQL_ROOT_PASSWORD" --silent; do
  sleep 2
done
echo "[OK] MySQL prêt"

echo "[2/3] Génération des prévisions (job quotidien)..."
python -m deploy.app.forecast_job

echo "[3/3] Démarrage de l'API sur 0.0.0.0:8000..."
cd /app/deploy
exec python -m uvicorn app.api:app --host 0.0.0.0 --port 8000