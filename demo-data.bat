@echo off
rem Smart Parking - load DEMO data (simulated cameras, sample users and history).
rem Everything it adds is marked SIM. Do not use on a live site.
cd /d "%~dp0"
echo  This adds simulated demo cameras, demo users and 14 days of sample history.
echo  Everything is marked SIM. Press Ctrl+C to cancel, or
pause
docker compose exec app python -m app.seed
pause
