# Windows setup (PowerShell, run from the project root)
# Prerequisites: Python 3.11+, Node.js 20+, PostgreSQL 14+ (https://www.postgresql.org/download/windows/)
$ErrorActionPreference = "Stop"

# 1. Database (adjust the path to psql.exe if needed)
& psql -U postgres -c "CREATE USER parking WITH PASSWORD 'parking';"
& psql -U postgres -c "CREATE DATABASE smart_parking OWNER parking;"

# 2. Backend
Set-Location backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
# Optional real ANPR engine:  .\.venv\Scripts\pip install -r requirements-ai.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Edit backend\.env (SECRET_KEY, DATABASE_URL)" }
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m app.seed --days 14
Set-Location ..

# 3. Frontend (production build is served by the backend)
Set-Location frontend
npm ci
npm run build
Set-Location ..
Write-Host "Done. Start with: deploy\windows-start.ps1  ->  http://localhost:8000"
