# Smart Parking Management System with ANPR

A working parking management application. It connects to IP / ONVIF ANPR cameras over RTSP, reads registration numbers with **YOLO + PaddleOCR**, counts every vehicle entering and leaving with **5-layer duplicate prevention**, and shows live occupancy, camera feeds, history, alerts and reports on a real-time **React** dashboard backed by **FastAPI + PostgreSQL**.

A **camera simulation mode** lets you run and test everything without camera hardware. Simulated results are labelled and stored separately from real camera results.

| | |
|---|---|
| Frontend | React 18 · Vite · Tailwind CSS · Recharts · WebSocket live updates |
| Backend | Python FastAPI · REST · WebSocket · JWT + bcrypt · RBAC (4 roles) |
| ANPR | YOLO (Ultralytics) vehicle detection · OpenCV / YOLO plate localisation · PaddleOCR · IoU tracker with plate voting |
| Cameras | RTSP (TCP, auto-reconnect), ONVIF discovery and stream lookup, multiple simultaneous cameras, MJPEG live view |
| Database | PostgreSQL · SQLAlchemy 2 · Alembic migrations |
| Reports | 10 report types → Excel, PDF, CSV, with charts |
| Deploy | Docker Compose · Linux systemd + nginx · Windows (PowerShell / NSSM) · cloud VM |

## Easiest start (Windows)

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and [Git](https://git-scm.com/download/win).
2. Download the project: `git clone https://github.com/siv151992-lang/parking.git` (into your user folder, not `C:\Windows\System32`).
3. Double-click **`start.bat`**. The first start builds everything (10–20 minutes). The browser then opens <http://localhost:8000>; log in as `admin` / `Admin@123`.

| File | What it does |
|---|---|
| `start.bat` | Starts Docker Desktop if needed, creates the settings file, builds and starts the app, opens the browser |
| `stop.bat` | Stops the app (data is kept) |
| `update.bat` | Downloads the latest version and restarts |
| `demo-data.bat` | Optional: adds simulated demo cameras and sample history (all marked SIM) |

On macOS / Linux, run `./start.sh` instead.

## Set up your car park

1. **Parking Spaces → Add row**: one entry per row (e.g. *Row A*, 40 spaces).
2. **Cameras → Add camera**: name, *Camera position*, IP address, username and password. The video address is found automatically.
   * *Main gate · vehicles coming in / going out*: counts the whole car park.
   * *Row A · vehicles driving into / leaving the row*: counts the free spaces of Row A.
   * Many cameras at once: **Cameras → Add many**. Paste rows from Excel (Name, Position, IP address, Username, Password) or upload an .xlsx / .csv file (*Download template* gives the format). Every line is checked, including whether the camera answers, before anything is saved.
3. The **Dashboard** shows the free spaces, the vehicles inside, and the free spaces of every row, live.

If a row camera was offline, correct the row's count under **Parking Spaces → Rows** (the sliders button).

## Folder structure

```
smart-parking/
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app, WebSocket, startup, maintenance loop
│   │   ├── config.py          Settings from .env
│   │   ├── models.py          Database models (users, cameras, vehicles, vehicle_detections,
│   │   │                      parking_sessions, entry/exit_transactions, parking_capacity, alerts, audit_logs)
│   │   ├── schemas.py         Request validation
│   │   ├── security.py        bcrypt, JWT, role → permission map
│   │   ├── api/               REST routers (auth, users, cameras, dashboard, transactions, vehicles,
│   │   │                      detections, occupancy, reports, alerts, settings/audit/media)
│   │   ├── services/
│   │   │   ├── counting.py    ★ counting engine: entries, exits, duplicates, matching, corrections
│   │   │   ├── occupancy.py   capacity, alerts, reconciliation
│   │   │   ├── reports.py     report builders + CSV / Excel / PDF exporters
│   │   │   └── events.py      post-commit WebSocket broadcasting
│   │   ├── anpr/
│   │   │   ├── engine.py      YOLO + plate localisation + PaddleOCR
│   │   │   ├── tracker.py     vehicle tracking, detection zone, trigger line, plate voting
│   │   │   ├── worker.py      per-camera capture/process thread with reconnect
│   │   │   ├── sources.py     RTSP / file capture (latest-frame grabber)
│   │   │   ├── simulator.py   simulated camera
│   │   │   └── onvif.py       WS-Discovery + ONVIF stream URIs
│   │   └── seed.py            sample data loader
│   ├── alembic/               database migrations
│   ├── tests/                 45 pytest tests
│   ├── requirements.txt       core dependencies
│   ├── requirements-ai.txt    + YOLO / PaddleOCR / ONVIF
│   └── .env.example
├── frontend/                  React app (11 pages)
│   ├── src/pages/             Dashboard, LiveMonitoring, CameraManagement, Transactions (Entry/Exit),
│   │                          VehicleHistory, Occupancy, Reports, Alerts, Users, Settings, Login
│   └── package.json
├── docs/                      ARCHITECTURE · API · CAMERAS · DEPLOYMENT · TESTING
├── deploy/                    systemd unit, nginx config, Windows scripts
├── Dockerfile, docker-compose.yml
```

## Quick start (development)

Prerequisites: Python 3.11+, Node.js 20+, PostgreSQL 14+.

### 1. Database setup

```bash
sudo -u postgres psql -c "CREATE USER parking WITH PASSWORD 'parking';"
sudo -u postgres psql -c "CREATE DATABASE smart_parking OWNER parking;"
```

On Windows, run the same two statements in *SQL Shell (psql)* as the `postgres` user.

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt        # core: API, simulation, video streaming, reports
pip install -r requirements-ai.txt     # optional: real ANPR engine (YOLO + PaddleOCR + ONVIF)
cp .env.example .env                   # then set DATABASE_URL and SECRET_KEY
alembic upgrade head                   # create tables (also runs automatically on start)
python -m app.seed --days 14           # optional: users, 3 simulated cameras, 14 days of history
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API docs: <http://localhost:8000/docs>

### 3. Frontend

```bash
cd frontend
npm install
npm run dev                            # http://localhost:5173 (proxies /api and /ws to :8000)
```

For production, run `npm run build`; the backend then serves the UI itself at <http://localhost:8000>.

### 4. Log in

| User | Password | Role |
|---|---|---|
| `admin` | `Admin@123` | Super Admin (created on first start; change the password!) |
| `manager` | `Manager@123` | Parking Manager (seed) |
| `operator` | `Operator@123` | Security Operator (seed) |
| `viewer` | `Viewer@123` | Report Viewer (seed) |

## How counting works

```
Vehicles Inside = Total valid entries − Total counted exits = ACTIVE parking sessions
```

* **Entry camera**: detect vehicle → track → crop plate → OCR (voted across frames) → classify type → save images, timestamp, camera and confidence → create session + entry transaction → count +1 → push to every dashboard.
* **Exit camera**: recognise plate → find the active session (exact → OCR-fuzzy → unread session) → record exit time and duration → close the session → count −1 → push to dashboards.
* **Duplicates are prevented** by tracking (one event per vehicle), the detection zone and trigger line, a per-plate cooldown that spans cameras, transaction validation, and a database unique constraint.
* The count **never goes negative**: exits only decrement when they close an active session. Unmatched exits are flagged for an operator to resolve.
* **Failed reads** are still counted and queued for review. Every **manual correction** is permission-checked and audit-logged.
* A background job reconciles the counts every minute.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## Documentation

* [Architecture & database design](docs/ARCHITECTURE.md)
* [API reference (REST + WebSocket)](docs/API.md)
* [Camera configuration & simulation mode](docs/CAMERAS.md)
* [Testing](docs/TESTING.md)
* [Deployment: Docker, Linux, Windows, cloud](docs/DEPLOYMENT.md)
