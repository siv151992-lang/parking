@echo off
rem Smart Parking - download the latest version and restart.
cd /d "%~dp0"
echo  Downloading the latest version...
git pull
if errorlevel 1 (
  echo  Could not download the update. Check the internet connection.
  pause
  exit /b 1
)
call "%~dp0start.bat"
