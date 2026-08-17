@echo off
rem ============================================================
rem  STEG HelioCast AI - Demarrage Docker (MySQL + API + site)
rem  Pre-requis : Docker Desktop installe et demarre
rem  Double-cliquez : build + lancement + ouverture navigateur
rem ============================================================
setlocal

echo ============================================
echo   STEG HelioCast AI - Demarrage Docker
echo ============================================
echo.

docker info >nul 2>&1
if errorlevel 1 (
  echo [!!]  Docker n'est pas disponible.
  echo       Veuillez demarrer Docker Desktop puis relancer ce fichier.
  goto end
)
echo [OK]  Docker detecte

echo [..]  Construction des images (premiere fois : quelques minutes)...
docker compose -f deploy\docker-compose.yml up -d --build
if errorlevel 1 (
  echo [!!]  Echec du build/demarrage. Verifiez Docker.
  goto end
)
echo [OK]  Conteneurs demarres

echo [..]  Attente du service web...
ping -n 5 127.0.0.1 >nul
curl -s -o nul http://127.0.0.1:8000/health
if errorlevel 1 (
  ping -n 12 127.0.0.1 >nul
)
echo [OK]  Dashboard : http://127.0.0.1:8000/

start "" http://127.0.0.1:8000/

echo.
echo  Pour arreter :  docker compose -f deploy\docker-compose.yml down
echo  Pour relancer le job a la main :
echo    docker exec heliocast-api python -m deploy.app.forecast_job
echo.

:end
ping -n 6 127.0.0.1 >nul
endlocal