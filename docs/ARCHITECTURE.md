# System Architecture

## Overview

```
 ┌───────────────┐  RTSP/H.264   ┌──────────────────────────── FastAPI process ────────────────────────────┐
 │ ANPR IP camera├──────────────►│ CameraWorker thread (1 per camera)                                       │
 │ (ENTRY / EXIT)│               │  OpenCVSource ─► latest frame ─► ANPREngine (YOLO + plate locator +      │
 └───────────────┘               │    grabber thread                PaddleOCR)  ── or ── SimulatedSource    │
 ┌───────────────┐  sim://       │                     │ detections                    ground-truth dets    │
 │ Simulator     ├──────────────►│                     ▼                                                    │
 └───────────────┘               │  VehicleTracker (IoU tracks, zone, trigger line, plate voting)          │
                                 │                     │ ONE TrackEvent per physical vehicle               │
                                 │                     ▼                                                    │
                                 │  services/counting.py  (global lock, cooldown, validation, matching)    │
                                 │                     │ SQL transaction                                    │
                                 │                     ▼                                                    │
                                 │  PostgreSQL ◄───────┘        after_commit ─► WebSocket broadcast ──────►│──► React dashboards
                                 │                                                                          │
                                 │  REST API (/api/*)  ◄── React SPA (Vite/Tailwind/Recharts) ─────────────│
                                 │  MJPEG /api/cameras/{id}/stream  (annotated live video)                  │
                                 └──────────────────────────────────────────────────────────────────────────┘
```

| Layer | Technology | Location |
|---|---|---|
| Frontend | React 18, React Router, Tailwind CSS, Recharts, lucide icons | `frontend/src` |
| REST API | FastAPI, Pydantic v2, JWT (PyJWT), bcrypt | `backend/app/api` |
| Real-time | WebSocket `/ws`, events sent only after DB commit | `backend/app/services/events.py` |
| ANPR | Ultralytics YOLO, PaddleOCR, OpenCV | `backend/app/anpr` |
| Counting | Session-based counting engine | `backend/app/services/counting.py` |
| Database | PostgreSQL 14+ (SQLAlchemy 2, Alembic) | `backend/app/models.py`, `backend/alembic` |
| Reports | openpyxl (Excel), reportlab (PDF), csv | `backend/app/services/reports.py` |

## Processing pipeline (per camera)

1. **Capture**: `OpenCVSource` opens the RTSP URL over TCP. A grabber thread keeps only the newest frame, so slow inference never makes the video fall behind. If no frame arrives for 10 s the stream is treated as lost.
2. **Detect**: each camera is analysed `ANALYSIS_FPS` times per second (default 8; other frames are decoded but not converted). YOLO runs only while a cheap frame-difference check sees motion in the detection zone, while a vehicle is tracked, or at least every 3 s (`MOTION_GATE`). It detects car / motorcycle / bus / truck (mapped to CAR / TWO_WHEELER / COMMERCIAL).
3. **Locate plate**: a dedicated plate YOLO model if one is configured. Otherwise OpenCV morphology (black-hat, Sobel, aspect-ratio filter), with PaddleOCR text detection on the lower half of the vehicle as the fallback.
4. **OCR**: PaddleOCR on the CLAHE-enhanced crop. Two-row plates are merged top-to-bottom, then the text is normalised to `[A-Z0-9]`.
5. **Track**: the IoU tracker gives each physical vehicle a track. OCR reads are collected on the track across frames.
6. **Trigger**: the track fires exactly **once**, when its bottom-centre crosses the trigger line inside the detection zone (`line`), or after it has waited in the zone with enough consistent reads (`presence`, for barrier gates).
7. **Vote**: a confidence-weighted whole-string vote decides the plate, with a per-character vote as the fallback when reads disagree.
8. **Count**: `process_detection()` applies cooldown, validation and matching, writes the detection, session and transaction rows, then commits.
9. **Broadcast**: after commit, `detection`, `entry`/`exit`, `occupancy` and `alert` events go out to every WebSocket client.

## Duplicate prevention (5 layers)

| # | Layer | Prevents |
|---|---|---|
| 1 | Tracker: one event per track | A vehicle standing in front of the camera being counted on every frame |
| 2 | Detection zone + trigger line | Vehicles passing in the background, or vehicles that reverse out |
| 3 | Cooldown (per camera, same plate, same direction, **any** camera) | Track re-acquisition after occlusion; two entry cameras watching the same lane |
| 4 | Transaction validation | ENTRY while an ACTIVE session exists → `DUPLICATE` + alert. EXIT only counts when it closes a session |
| 5 | Partial unique index `uq_active_session_per_plate` | Races between processes or servers (DB-level guarantee) |

Counting decisions are also serialised in-process with a lock, and use `SELECT … FOR UPDATE` on PostgreSQL.

## Counting model

* **Vehicles inside = number of ACTIVE parking sessions.** This is the single source of truth, so it can never go negative or drift.
* It always equals `valid entries − counted exits`. The `/api/occupancy/reconcile` endpoint and a once-a-minute maintenance job verify this, and raise a `COUNT_MISMATCH` alert if it ever fails.
* **Exit matching order**: exact plate → fuzzy match (OCR-confusable characters folded, edit distance ≤ 1, accepted only if exactly one candidate) → oldest *unread* session of the same category → `UNMATCHED`.
* An `UNMATCHED` exit is recorded and alerted but **does not** reduce the count. An operator links it to a session via *Vehicle Exit → Resolve*, which suggests the closest candidates.
* **Failed OCR on entry**: the vehicle is still counted (session with no plate, `needs_review`) and an `OCR_FAILED` alert is raised. Correcting the plate in the Review Queue updates the session.
* **Re-entry after a missed exit**: if the plate's active session is older than `reentry_auto_close_minutes`, the old session is closed as `AUTO_CLOSED` (flagged for review) and a new one is opened. If it is newer, the entry is rejected as a duplicate.
* **Manual corrections**: manual entry/exit, cancel entry, cancel exit (re-opens the session), resolve unmatched exit, correct plate. Every one requires a permission and writes an `audit_logs` row.

## Real vs simulated data

Simulated cameras (`is_simulated=true`) render synthetic traffic and produce detections with realistic noise. Every row they create is flagged: `vehicle_detections.is_simulated`, `parking_sessions.is_simulated`, transaction `source = SIMULATED`, and `alerts.is_simulated`. The UI shows a purple **SIM** badge, video frames carry a *SIMULATED* watermark, and reports and session search can exclude simulated data (*Data source → Real cameras only*).

## Database schema

```
users ─┐
       ├─< audit_logs
cameras ─┬─< vehicle_detections >─ vehicles
         ├─< entry_transactions >─ parking_sessions >─ vehicles
         ├─< exit_transactions  >─┘
         └─< alerts
parking_capacity (one row per category: CAR, TWO_WHEELER, HEAVY, RESERVED)
system_settings (key/value JSONB)
```

| Table | Purpose | Key indexes / constraints |
|---|---|---|
| `users` | Accounts, role, bcrypt hash, lockout counters | unique `username`, `email` |
| `cameras` | Camera config, RTSP, direction, zone (JSONB), cooldown, live status | unique `camera_code` |
| `vehicles` | One row per plate: type, reserved / blacklisted flags, visit stats | unique `plate_number` |
| `vehicle_detections` | Every ANPR event, including duplicates and cooldown hits, with images and confidence | `(camera_id, detected_at)`, `(plate_number, detected_at)`, `needs_review` |
| `parking_sessions` | One stay: entry → exit, duration, images | **partial unique** `(plate_number) WHERE status='ACTIVE'`, `(status, category)` |
| `entry_transactions` | Entry events (ANPR / SIMULATED / MANUAL) | `(timestamp, status)`, `plate_number`, FK session |
| `exit_transactions` | Exit events with match method | `(timestamp, status)`, `plate_number`, FK session (nullable for UNMATCHED) |
| `parking_capacity` | Capacity and alert threshold per category, plus alert hysteresis state | unique `category` |
| `alerts` | Notifications | `created_at`, `(alert_type, is_resolved)` |
| `audit_logs` | Every login, config change and manual correction | `created_at`, `(entity_type, entity_id)` |
| `system_settings` | Runtime-editable rules | PK `key` |

All timestamps are `timestamptz` (UTC). "Today" and report periods use the facility timezone (setting `timezone`).
