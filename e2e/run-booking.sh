#!/bin/bash
# Fresh demo database, start the app, run the office-parking browser workflows, stop the app.
set -e
DB=${E2E_DB:-e2e_booking}
cd "$(dirname "$0")/../backend"
PY=${PYTHON:-python}
su postgres -c "psql -q -c 'DROP DATABASE IF EXISTS $DB' -c 'CREATE DATABASE $DB OWNER parking'" 2>/dev/null || { dropdb --if-exists $DB; createdb $DB; }
export DATABASE_URL=postgresql+psycopg2://parking:parking@localhost:5432/$DB CAMERA_WORKERS_ENABLED=false
$PY -m app.seed --days 1 --no-history >/dev/null
$PY -m uvicorn app.main:app --host 127.0.0.1 --port ${PORT:-8000} > /tmp/e2e-booking-server.log 2>&1 &
PID=$!
trap 'kill $PID' EXIT
until curl -s 127.0.0.1:${PORT:-8000}/api/health | grep -q ok; do sleep 1; done
node ../e2e/booking.js
