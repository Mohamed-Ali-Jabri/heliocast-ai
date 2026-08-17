@echo off
rem ============================================================
rem  STEG HelioCast AI - Demarrage complet MySQL + API + site
rem  Double-cliquez sur ce fichier : tout se lance tout seul.
rem ============================================================
setlocal

echo ============================================
echo   STEG HelioCast AI - Demarrage du service
echo ============================================
echo.

rem -------- 1 - MySQL XAMPP --------
netstat -an | findstr ":3306" | findstr "LISTENING" >nul
if errorlevel 1 goto start_mysql
echo [OK]  MySQL deja demarre
goto api_step

:start_mysql
echo [..]  Demarrage de MySQL XAMPP...
start "MySQL XAMPP" "c:\xampp\mysql\bin\mysqld.exe" --defaults-file=c:\xampp\mysql\bin\my.ini --standalone
ping -n 7 127.0.0.1 >nul

rem -------- 2 - API FastAPI --------
:api_step
netstat -an | findstr ":8000" | findstr "LISTENING" >nul
if errorlevel 1 goto start_api
echo [OK]  API HelioCast deja demarree
goto open_site

:start_api
echo [..]  Demarrage de l'API uvicorn dans une fenetre...
if exist "C:\Program Files\Python314\python.exe" goto py_full
start "API HelioCast" /d "%CD%\deploy" cmd /k "python -m uvicorn app.api:app --host 127.0.0.1 --port 8000"
goto open_site

:py_full
start "API HelioCast" /d "%CD%\deploy" cmd /k ""C:\Program Files\Python314\python.exe" -m uvicorn app.api:app --host 127.0.0.1 --port 8000"
ping -n 9 127.0.0.1 >nul

rem -------- 3 - Verification et ouverture --------
:open_site
netstat -an | findstr ":8000" | findstr "LISTENING" >nul
if errorlevel 1 goto fail
echo [OK]  Dashboard pret : http://127.0.0.1:8000/
start "" http://127.0.0.1:8000/
goto end

:fail
echo [!!]  L'API n'a pas demarre, verifiez la fenetre API.
goto end

:end
echo.
echo  Astuce : actualiser les previsions avec :
echo    python -m deploy.app.forecast_job
echo.
ping -n 6 127.0.0.1 >nul
endlocal