"""FastAPI application entrypoint."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .anpr.manager import camera_manager
from .api import admin, alerts, auth, cameras, cameras_bulk, dashboard, office_parking, detections, occupancy, reports, rows, transactions, users, vehicles
from .config import BASE_DIR, settings
from .database import SessionLocal, engine
from .models import Alert, AlertType, ParkingSession, Role, SessionStatus, Severity, User, VehicleDetection
from .security import hash_password
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
                        role=Role.SUPER_ADMIN, hashed_password=hash_password(settings.ADMIN_PASSWORD),
                        must_change_password=settings.ADMIN_PASSWORD == "Admin@123"))
            log.warning("Created initial super admin '%s' - change the password after first login!", settings.ADMIN_USERNAME)
        else:
            owner = db.query(User).order_by(User.id).first()
            if owner.role != Role.SUPER_ADMIN or not owner.is_active:
                owner.role, owner.is_active = Role.SUPER_ADMIN, True
                log.warning("Restored owner account '%s' to active Super Admin", owner.username)
        ensure_capacity_rows(db)
        # move login details typed into camera URLs into the username / password fields
        from .anpr.sources import split_credentials
        from .models import Camera
        for cam in db.query(Camera).filter(Camera.rtsp_url.like("%@%")).all():
            clean, user, pw = split_credentials(cam.rtsp_url)
            if user:
                cam.rtsp_url, cam.username, cam.password = clean, user, pw or cam.password
        db.commit()
    finally:
        db.close()


def purge_old_detections(db, retention_days: int, batch: int = 2000, budget_seconds: float = 30.0) -> int:
    """Delete raw detections older than the retention period (transactions and sessions are kept),
    with their image files, except images that are a parking session's entry / exit evidence."""
    import time

    from sqlalchemy import or_

    cutoff = utcnow() - timedelta(days=retention_days)
    deadline = time.monotonic() + budget_seconds
    removed = 0
    while time.monotonic() < deadline:
        old = db.query(VehicleDetection).filter(VehicleDetection.detected_at < cutoff).order_by(VehicleDetection.id).limit(batch).all()
        if not old:
            break
        paths = {p for d in old for p in (d.vehicle_image_path, d.plate_image_path) if p}
        keep = set()
        if paths:
            cols = (ParkingSession.entry_vehicle_image, ParkingSession.entry_plate_image,
                    ParkingSession.exit_vehicle_image, ParkingSession.exit_plate_image)
            for row in db.query(*cols).filter(or_(*(c.in_(paths) for c in cols))):
                keep.update(p for p in row if p)
        for d in old:
            db.delete(d)
        db.commit()
        for p in paths - keep:
            (Path(settings.MEDIA_DIR) / p).unlink(missing_ok=True)
        removed += len(old)
    if removed:
        log.info("Retention: removed %d detections older than %d days", removed, retention_days)
    return removed


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
        from .services.bookings import sweep as booking_sweep
        booking_sweep(db)
        if utcnow() - state.get("last_purge", utcnow() - timedelta(days=2)) > timedelta(hours=24):
            purge_old_detections(db, int(cfg["detection_retention_days"]))
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
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https://tile.openstreetmap.org; connect-src 'self' ws: wss:; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


class SecurityHeaders:
    """Adds browser security headers to every HTTP response (pure ASGI, so streams are untouched)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        docs = scope["path"].startswith(("/docs", "/redoc"))  # Swagger / ReDoc load their scripts from a CDN

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                            (b"referrer-policy", b"no-referrer"),
                            (b"permissions-policy", b"camera=(self), microphone=(), geolocation=(self)")]
                if not docs:
                    headers.append((b"content-security-policy", CSP.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins_list, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])
app.add_middleware(SecurityHeaders)

for r in (auth, users, cameras, cameras_bulk, office_parking, dashboard, transactions, vehicles, detections, occupancy, rows, reports, alerts, admin):
    app.include_router(r.router)


@app.get("/api/health", tags=["System"])
def health():
    with engine.connect() as c:
        c.exec_driver_sql("SELECT 1")
    return {"status": "ok", "cameras_running": len(camera_manager.workers)}


def _ws_user(token: str) -> dict | None:
    """Check a WebSocket's token like any API request (signature, expiry, active user, session not ended)."""
    from fastapi import HTTPException

    from .deps import user_from_token

    db = SessionLocal()
    try:
        u = user_from_token(token, db)
        return {"user_id": str(u.id), "role": u.role, "username": u.username}
    except HTTPException:
        return None
    finally:
        db.close()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Real-time events: entry, exit, detection, occupancy, camera_status, alert.
    After connecting, send {"type": "auth", "token": "<JWT>"} within 10 s (the token is not put
    in the URL, where it would end up in logs). Then send "ping" to receive {"type": "pong"}."""
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=10)
        token = first.get("token", "") if isinstance(first, dict) and first.get("type") == "auth" else ""
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, KeyError):
        token = ""
    info = await asyncio.to_thread(_ws_user, token) if token else None
    if info is None:
        await ws.close(code=4401)
        return
    await events.manager.connect(ws, info, accepted=True)
    try:
        await ws.send_json({"type": "hello", "data": {"user": info["username"]}})
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
