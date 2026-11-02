"""Real-time event bus.

Events are queued on the SQLAlchemy session and only broadcast to WebSocket
clients *after* the transaction commits, so the dashboard never shows data
that was rolled back. Broadcasting is thread-safe: camera worker threads can
emit events which are delivered on the asyncio loop.
"""
import asyncio
import json
import logging
import threading
from datetime import date, datetime, timezone

from fastapi import WebSocket
from sqlalchemy import event
from sqlalchemy.orm import Session

log = logging.getLogger("events")


def _default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"Not serialisable: {type(o)}")


class ConnectionManager:
    def __init__(self):
        self._clients: dict[WebSocket, dict] = {}
        self._lock = threading.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket, user_info: dict):
        await ws.accept()
        with self._lock:
            self._clients[ws] = user_info

    def disconnect(self, ws: WebSocket):
        with self._lock:
            self._clients.pop(ws, None)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def _send_all(self, message: str):
        with self._lock:
            clients = list(self._clients)
        dead = []
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast(self, event_type: str, data: dict):
        """Thread-safe broadcast; callable from any thread."""
        if self.loop is None or self.loop.is_closed():
            return
        message = json.dumps({"type": event_type, "data": data, "ts": datetime.now(timezone.utc).isoformat()}, default=_default)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.loop.create_task(self._send_all(message))
        else:
            asyncio.run_coroutine_threadsafe(self._send_all(message), self.loop)


manager = ConnectionManager()


def emit(db: Session, event_type: str, data: dict):
    """Queue an event to be broadcast once `db` commits."""
    db.info.setdefault("pending_events", []).append((event_type, data))


def emit_now(event_type: str, data: dict):
    manager.broadcast(event_type, data)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session):
    pending = session.info.pop("pending_events", [])
    for event_type, data in pending:
        try:
            manager.broadcast(event_type, data)
        except Exception:  # never break a commit because of a websocket
            log.exception("broadcast failed")


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session):
    session.info.pop("pending_events", None)
