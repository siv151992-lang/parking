"""FastAPI application entrypoint."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import jwt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .anpr.manager import camera_manager
from .api import admin, alerts, auth, cameras, dashboard, detections, occupancy, reports, transactions, users, vehicles
from .config import BASE_DIR, settings
from .database import SessionLocal, engine
from .models import Alert, AlertType, DetectionStatus, ParkingSession, Role, SessionStatus, Severity, User, VehicleDetection
from .security import decode_token, hash_password
from .services import events, settings_store
from .services.alerts import create_alert
from .services.occupancy import ensure_capacity_rows, reconcile
from .services.timeutil import utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("app")


def run_migrations():
    if settings.DATABASE_URL.startswith("sqlite"):
        from .database import Base
        Base.metadata.create_all(engine)
        return
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))
    command.upgrade(cfg, "head")


def bootstrap():
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            db.add(User(username=settings.ADMIN_USERNAME, email=settings.ADMIN_EMAIL, full_name="Super Administrator",
                        role=Role.SUPER_ADMIN, hashed_password=hash_password(settings.ADMIN_PASSWORD)))
            log.warning("Created initial super admin '%s' - change the password after first login!", settings.ADMIN_USERNAME)
        ensure_capacity_rows(db)
        db.commit()
    finally:
        db.close()


def maintenance_tick(state: dict):
    """Runs every minute: reconciliation, overstay detection, retention."""
    db = SessionLocal()
    try:
        cfg = settings_store.get_all(db)
        rec = reconcile(db)
        if not rec["is_consistent"]:
            create_alert(db, AlertType.COUNT_MISMATCH, Severity.CRITICAL, "Vehicle count mismatch detected",
                         f"Entries - exits = {rec['expected_inside']} but {rec['active_sessions']} active sessions.",
                         data=rec, dedupe_seconds=3600)
        limit = utcnow() - timedelta(hours=float(cfg["max_parking_hours"]))
        overstays = db.query(ParkingSession).filter(ParkingSession.status == SessionStatus.ACTIVE, ParkingSession.entry_time < limit).limit(200).all()
        if overstays:
            alerted = {sid for (sid,) in db.query(Alert.session_id).filter(
                Alert.alert_type == AlertType.SUSPICIOUS_VEHICLE, Alert.session_id.in_([s.id for s in overstays]))}
            for s in overstays:
                if s.id not in alerted:
                    create_alert(db, AlertType.SUSPICIOUS_VEHICLE, Severity.WARNING,
                                 f"Overstay: {s.plate_number or 'unread vehicle'} parked > {cfg['max_parking_hours']}h",
                                 f"Inside since {s.entry_time:%Y-%m-%d %H:%M} UTC (session #{s.id}).",
                                 session_id=s.id, plate_number=s.plate_number, is_simulated=s.is_simulated,
                                 data={"reason": "overstay"})
        if utcnow() - state.get("last_purge", utcnow() - timedelta(days=2)) > timedelta(hours=24):
            cutoff = utcnow() - timedelta(days=int(cfg["detection_retention_days"]))
            old = db.query(VehicleDetection).filter(VehicleDetection.detected_at < cutoff,
                                                    VehicleDetection.status.in_([DetectionStatus.COOLDOWN, DetectionStatus.DUPLICATE]))
            for d in old.limit(5000).all():
                for p in (d.vehicle_image_path, d.plate_image_path):
                    if p:
                        (Path(settings.MEDIA_DIR) / p).unlink(missing_ok=True)
                db.delete(d)
            state["last_purge"] = utcnow()
        db.commit()
    except Exception:
        db.rollback()
        log.exception("maintenance failed")
    finally:
        db.close()


async def maintenance_loop():
    state: dict = {}
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(maintenance_tick, state)


@asynccontextmanager
async def lifespan(app: FastAPI):
    events.manager.loop = asyncio.get_running_loop()
    if settings.AUTO_MIGRATE:
        await asyncio.to_thread(run_migrations)
    await asyncio.to_thread(bootstrap)
    if settings.CAMERA_WORKERS_ENABLED:
        await asyncio.to_thread(camera_manager.start_all)
    task = asyncio.create_task(maintenance_loop())
    yield
    task.cancel()
    await asyncio.to_thread(camera_manager.stop_all)


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Smart Parking Management System with ANPR camera integration. "
                "Authenticate with POST /api/auth/login, then use the bearer token.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

for r in (auth, users, cameras, dashboard, transactions, vehicles, detections, occupancy, reports, alerts, admin):
    app.include_router(r.router)


@app.get("/api/health", tags=["System"])
def health():
    with engine.connect() as c:
        c.exec_driver_sql("SELECT 1")
    return {"status": "ok", "cameras_running": len(camera_manager.workers)}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = ""):
    """Real-time events: entry, exit, detection, occupancy, camera_status, alert.
    Connect with ws://host/ws?token=<JWT>."""
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        await ws.close(code=4401)
        return
    await events.manager.connect(ws, {"user_id": payload["sub"], "role": payload.get("role")})
    try:
        await ws.send_json({"type": "hello", "data": {"user": payload.get("username")}})
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_json({"type": "pong", "data": {}})
    except WebSocketDisconnect:
        pass
    finally:
        events.manager.disconnect(ws)


# Serve the built React app (frontend/dist) for single-server deployments.
DIST = BASE_DIR.parent / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(("api/", "ws")):
            from fastapi import HTTPException
            raise HTTPException(404, "Not found")
        f = DIST / full_path
        if full_path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
