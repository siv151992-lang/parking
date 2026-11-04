# Deployment

The backend is a **single process**: the REST API, WebSocket hub and the camera worker threads run together. Run **one** uvicorn worker per site. Scale ANPR throughput with a GPU (`YOLO_DEVICE=cuda:0`, `paddlepaddle-gpu`) or a lower `ANALYSIS_FPS`, not with more web workers. In production, the built React app is served by the same process from `frontend/dist`.

Sizing guide (CPU-only, YOLOv8n): decoding a 1080p H.264 stream costs roughly 5–10% of one core per camera all the time; YOLO + OCR only run while something moves at that camera (motion gate). A 4–8 core PC handles 10–20 gate / row cameras at typical parking traffic. Live video is only drawn while someone watches it: the Live Cameras grid shows pictures refreshed once a second, and full video opens per camera.

## Option A: Docker (Linux or Windows with Docker Desktop)

```bash
cp backend/.env.example .env                     # compose reads SECRET_KEY etc. from ./.env
echo "SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" >> .env
docker compose up -d --build
docker compose exec app python -m app.seed       # optional sample data
```

**Real ANPR engine (needed for real cameras to read plates).** Add `WITH_AI=true` to `.env` and rebuild with `docker compose up -d --build`. The build installs CPU-only PyTorch, YOLO and PaddleOCR (about 10–20 minutes, image about 3 GB) and downloads the models into the image, so it must reach `download.pytorch.org`, `github.com` and `paddleocr.bj.bcebos.com` over HTTPS.

Open `http://SERVER:8000`. Migrations run automatically on start (`AUTO_MIGRATE=true`).

## Option B: Linux server (Ubuntu 22.04/24.04)

```bash
sudo apt install -y python3-venv python3-dev postgresql nginx ffmpeg libgl1 nodejs npm
sudo -u postgres psql -c "CREATE USER parking WITH PASSWORD 'STRONG_PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE smart_parking OWNER parking;"

sudo useradd -r -m -d /opt/smart-parking parking
sudo cp -r . /opt/smart-parking && sudo chown -R parking /opt/smart-parking
cd /opt/smart-parking/backend
sudo -u parking python3 -m venv .venv
sudo -u parking .venv/bin/pip install -r requirements.txt      # + requirements-ai.txt for real ANPR
sudo -u parking cp .env.example .env   # set DATABASE_URL, SECRET_KEY, ADMIN_PASSWORD, CORS_ORIGINS
sudo -u parking .venv/bin/alembic upgrade head
cd ../frontend && sudo -u parking npm ci && sudo -u parking npm run build

sudo cp ../deploy/smart-parking.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now smart-parking
sudo cp ../deploy/nginx.conf /etc/nginx/sites-available/smart-parking
sudo ln -s /etc/nginx/sites-available/smart-parking /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d parking.example.com        # HTTPS
```

The nginx config disables buffering for MJPEG streams and upgrades `/ws` for WebSockets.

## Option C: Windows server

1. Install Python 3.11+, Node.js 20+, and PostgreSQL 16 (EDB installer; add `psql` to PATH).
2. From the project root in PowerShell: `powershell -ExecutionPolicy Bypass -File deploy\windows-setup.ps1`.
3. Edit `backend\.env` (SECRET_KEY, DATABASE_URL).
4. Start it with `deploy\windows-start.ps1`. To run it as a service, use [NSSM](https://nssm.cc/): `nssm install SmartParking <path>\backend\.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000`, with the start directory set to `backend`.
5. Allow TCP 8000 (or put IIS / nginx in front) in Windows Firewall. The server must reach the cameras on RTSP 554 and ONVIF 80.

## Cloud

Any VM works (AWS EC2, Azure VM, GCP, DigitalOcean). Use a managed PostgreSQL by setting `DATABASE_URL`. Cameras normally sit on a private network, so either:

* run the server on-premises (recommended for many cameras: bandwidth), or
* connect the site to the cloud VPC with a site-to-site VPN and use the private camera IPs.

**Never** expose RTSP cameras directly to the internet.

## Production checklist

- [ ] `SECRET_KEY` is a long random value; `ADMIN_PASSWORD` is changed after the first login
- [ ] HTTPS enabled (WebSocket becomes `wss://` automatically)
- [ ] `CORS_ORIGINS` is limited to your domain
- [ ] PostgreSQL backups, e.g. `pg_dump -Fc smart_parking > backup_$(date +%F).dump` daily
- [ ] `backend/media` (captured images) is on a disk with enough space; `detection_retention_days` is set
- [ ] Camera credentials use a read-only camera account
- [ ] Simulated cameras are disabled or removed in production (or kept clearly labelled for training)
