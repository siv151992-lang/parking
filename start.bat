@echo off
rem ============================================================
rem  Smart Parking - start (double-click this file)
rem  First run: builds the app (10-20 minutes). Later runs: seconds.
rem ============================================================
setlocal
cd /d "%~dp0"
title Smart Parking

echo.
echo  Smart Parking - starting...
echo.

rem ---- 1. Docker Desktop must be running
docker info >nul 2>&1
if errorlevel 1 (
  echo  Starting Docker Desktop...
  if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
    start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
  ) else (
    echo.
    echo  Docker Desktop is not installed.
    echo  Install it from https://www.docker.com/products/docker-desktop/ and run this file again.
    goto :fail
  )
  for /l %%i in (1,1,60) do (
    timeout /t 3 /nobreak >nul
    docker info >nul 2>&1 && goto :docker_ok
  )
  echo  Docker Desktop did not start. Open it by hand, wait until it says "Engine running", then run this file again.
  goto :fail
)
:docker_ok

rem ---- 2. Settings file (.env): created once, plain ASCII
findstr /b "SECRET_KEY=" .env >nul 2>&1
if errorlevel 1 (
  if exist .env move /y .env .env.old >nul
  echo  Creating settings file .env ...
  powershell -NoProfile -Command "$k=[guid]::NewGuid().ToString('N')+[guid]::NewGuid().ToString('N'); Set-Content -Path .env -Encoding ascii -Value @('SECRET_KEY='+$k, 'WITH_AI=true')"
)

rem ---- 3. Build and start
echo  Building and starting (the first time takes 10-20 minutes)...
docker compose up -d --build
if errorlevel 1 (
  echo.
  echo  The build failed. Scroll up for the error, or send a screenshot of it.
  goto :fail
)

rem ---- 4. Wait until the app answers, then open it
echo  Waiting for the app...
powershell -NoProfile -Command "for($i=0;$i -lt 90;$i++){try{if((Invoke-WebRequest -UseBasicParsing http://localhost:8000/api/health -TimeoutSec 2).StatusCode -eq 200){exit 0}}catch{}; Start-Sleep 2}; exit 1"
if errorlevel 1 (
  echo  The app did not answer. Showing its log:
  docker compose logs app --tail 40
  goto :fail
)
start "" http://localhost:8000
echo.
echo  ============================================================
echo   Smart Parking is running:  http://localhost:8000
echo   Login: admin / Admin@123   (change the password after login)
echo   It keeps running in the background. To stop it: stop.bat
echo  ============================================================
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
