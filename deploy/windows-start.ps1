# Starts the API (and the built web UI) on http://localhost:8000
Set-Location (Join-Path $PSScriptRoot "..\backend")
.\.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000
# To run as a Windows service, wrap this command with NSSM: nssm install SmartParking ...
