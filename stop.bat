@echo off
rem Smart Parking - stop. Your data is kept; start.bat starts it again.
cd /d "%~dp0"
docker compose stop
echo.
echo  Smart Parking stopped. Your data is kept.
pause
