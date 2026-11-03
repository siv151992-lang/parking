#!/usr/bin/env bash
# Smart Parking - start on macOS / Linux:  ./start.sh
set -e
cd "$(dirname "$0")"
if ! docker info >/dev/null 2>&1; then
  if command -v colima >/dev/null 2>&1; then
    echo "Starting Colima..."; colima start --cpu 4 --memory 6
  elif [ "$(uname)" = "Darwin" ] && [ -d "/Applications/Docker.app" ]; then
    echo "Starting Docker Desktop..."; open -a Docker
    for _ in $(seq 60); do sleep 3; docker info >/dev/null 2>&1 && break; done
  fi
  docker info >/dev/null 2>&1 || { echo "Docker is not running. Start Docker and run ./start.sh again."; exit 1; }
fi
if ! grep -q '^SECRET_KEY=' .env 2>/dev/null; then
  [ -f .env ] && mv .env .env.old
  printf 'SECRET_KEY=%s\nWITH_AI=true\n' "$(openssl rand -hex 32)" > .env
  echo "Created settings file .env"
fi
echo "Building and starting (the first time takes 10-20 minutes)..."
docker compose up -d --build
for _ in $(seq 90); do curl -fs http://localhost:8000/api/health >/dev/null && break; sleep 2; done
curl -fs http://localhost:8000/api/health >/dev/null || { docker compose logs app --tail 40; exit 1; }
echo
echo "Smart Parking is running: http://localhost:8000  (login admin / Admin@123)"
command -v open >/dev/null && open http://localhost:8000 || true
