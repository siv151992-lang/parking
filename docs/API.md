# API Documentation

Interactive OpenAPI documentation is generated automatically:

* Swagger UI: `http://<server>:8000/docs`
* ReDoc: `http://<server>:8000/redoc`
* OpenAPI JSON: `http://<server>:8000/openapi.json`

## Authentication

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Admin@123"}'
# → {"access_token":"eyJ...","token_type":"bearer","user":{...,"permissions":[...]}}
```

Send `Authorization: Bearer <token>` on every request. The access token is never accepted in a URL.

Endpoints used by `<img>` tags (MJPEG stream, snapshots, captured images) also accept `?token=<media token>`. Get one with `POST /api/auth/media-token`: it is valid for 60 minutes and can only open media, never call the API.

* After 5 failed logins an account is locked for 15 minutes (HTTP 423). After 30 failed logins from one address, that address is blocked for 15 minutes (HTTP 429).
* Logging in with the default password `Admin@123` sets `must_change_password`. Until the password is changed, every endpoint except `/api/auth/me`, `/api/auth/change-password` and `/api/auth/logout` answers `403 PASSWORD_CHANGE_REQUIRED`.
* Changing a password signs out every other session of that account (the response contains a new `access_token`). An admin resetting someone's password signs that user out.

## Endpoints

| Method | Path | Permission | Description |
|---|---|---|---|
| POST | `/api/auth/login` | – | Get a JWT |
| GET | `/api/auth/me` | any | Current user and permissions |
| POST | `/api/auth/logout` | any | Audit-logged logout |
| POST | `/api/auth/change-password` | any | Change own password; returns a new token, other sessions end |
| POST | `/api/auth/media-token` | any | 60-minute token for `<img>` URLs |
| GET | `/api/dashboard/stats` | dashboard.view | Entries / exits today, inside, capacity, available, occupancy %, type counts, cameras online / offline, duplicates blocked |
| GET | `/api/dashboard/hourly` | dashboard.view | Today's entries and exits per hour |
| GET | `/api/dashboard/recent-detections?limit=` | dashboard.view | Latest plate detections |
| GET | `/api/dashboard/system` | dashboard.view | ANPR engine status, workers, reconciliation |
| GET | `/api/cameras` | cameras.view | Cameras with live runtime (fps, reconnects, engine) |
| POST | `/api/cameras` | cameras.manage | Add camera |
| PUT | `/api/cameras/{id}` | cameras.manage | Update (worker restarts automatically when needed) |
| DELETE | `/api/cameras/{id}` | cameras.manage | Delete camera (history is kept) |
| POST | `/api/cameras/{id}/restart` | cameras.manage | Force reconnect |
| GET | `/api/cameras/{id}/stream` | cameras.view | MJPEG live stream with zone and track overlay |
| GET | `/api/cameras/{id}/snapshot` | cameras.view | Latest JPEG frame |
| POST | `/api/cameras/test-stream` | cameras.manage | Test an RTSP URL, returns a snapshot |
| POST | `/api/cameras/onvif/discover` | cameras.manage | WS-Discovery scan of the LAN |
| POST | `/api/cameras/onvif/probe` | cameras.manage | Get RTSP URIs from an ONVIF camera |
| POST | `/api/cameras/inject-detection` | cameras.manage | Push a SIMULATED pass through a camera's pipeline |
| GET | `/api/entries` | vehicles.view | Entry transactions (filters: plate, start, end, camera_id, vehicle_type, source, status, page) |
| POST | `/api/entries/manual` | transactions.manual | Manual entry |
| POST | `/api/entries/{id}/cancel` | transactions.correct | Cancel a false entry `{reason}` |
| GET | `/api/exits` | vehicles.view | Exit transactions (same filters) |
| POST | `/api/exits/manual` | transactions.manual | Manual exit `{plate_number \| session_id}` |
| POST | `/api/exits/{id}/cancel` | transactions.correct | Cancel exit, re-opens the session |
| GET | `/api/exits/{id}/candidates` | transactions.manual | Likely sessions for an unmatched exit |
| POST | `/api/exits/{id}/resolve` | transactions.manual | Link an unmatched exit to a session `{session_id}` |
| GET | `/api/unmatched-exits` | vehicles.view | Pending unmatched exits |
| GET | `/api/sessions` | vehicles.view | Parking sessions (plate, status, category, vehicle_type, start, end, needs_review, include_simulated) |
| GET | `/api/sessions/{id}` | vehicles.view | Session with its transactions |
| POST | `/api/sessions/{id}/plate` | detections.review | Correct the plate of a session |
| GET | `/api/vehicles` | vehicles.view | Vehicle registry (q, vehicle_type, flag=reserved\|blacklisted) |
| POST / PUT | `/api/vehicles[/{id}]` | vehicles.manage | Register / flag vehicles |
| GET | `/api/vehicles/history/{plate}` | vehicles.view | Full movement history and timeline |
| GET | `/api/detections` | vehicles.view | Raw detections (needs_review, is_simulated, status, …) |
| POST | `/api/detections/{id}/review` | detections.review | Confirm or correct `{corrected_plate, vehicle_type}` |
| GET | `/api/occupancy` | occupancy.view | Capacity, occupied, available, % per category |
| PUT | `/api/occupancy/{category}` | occupancy.manage | Set capacity / alert threshold |
| GET | `/api/occupancy/reconcile` | occupancy.view | entries − exits vs active sessions |
| GET | `/api/reports/types` | reports.view | Available reports |
| GET | `/api/reports/{type}?start=&end=&include_simulated=` | reports.view | Report JSON |
| GET | `/api/reports/{type}/export?format=csv\|xlsx\|pdf` | reports.view | Download |
| GET | `/api/alerts` | alerts.view | Alerts (alert_type, severity, resolved, unread) |
| POST | `/api/alerts/{id}/read`, `/api/alerts/read-all` | alerts.view | Mark read |
| POST | `/api/alerts/{id}/resolve` | alerts.manage | Resolve |
| GET / POST / PUT / DELETE | `/api/users…` | users.manage | User management |
| GET | `/api/users/roles` | users.manage | Role → permission matrix |
| GET / PUT | `/api/settings` | settings.view / settings.manage | Runtime rules |
| GET | `/api/audit-logs` | audit.view | Activity log |
| GET | `/api/media/{path}` | vehicles.view | Captured vehicle / plate image |
| GET | `/api/health` | – | Health check (DB connectivity) |

Report types: `daily_entry`, `daily_exit`, `hourly`, `weekly`, `monthly`, `category`, `camera`, `occupancy`, `peak_hours`, `accuracy`.

## Office parking

| Method | Path | Permission | Description |
|---|---|---|---|
| GET | `/api/auth/signup-info` | – | Whether employees can self-register, and the allowed email domains |
| POST | `/api/auth/register` | – | Employee self-registration `{full_name, email, password, phone, department}` |
| GET | `/api/offices?start=&end=&vehicle_type=` | offices.view | Offices with free / EV / accessible / visitor slot counts for the window |
| GET | `/api/offices/{id}/availability?start=&end=` | offices.view | Every slot with its state (AVAILABLE, BOOKED, OCCUPIED, MINE, ASSIGNED, OUT_OF_SERVICE); security also gets who is in it |
| POST / PUT / DELETE | `/api/offices[/{id}]` | offices.manage | Offices |
| POST | `/api/offices/{id}/floors`, `/api/floors/{id}/zones` | offices.manage | Add floor / zone; PUT / DELETE `/api/floors/{id}`, `/api/zones/{id}` |
| GET | `/api/offices/{id}/slots` | offices.manage | Slots of an office |
| POST | `/api/zones/{id}/slots` | offices.manage | Create slots in bulk `{prefix, start, count, digits, vehicle_type, is_ev, is_accessible, is_visitor}` |
| PUT / DELETE | `/api/slots/{id}` | offices.manage | Edit (incl. `assigned_user_id`, `status`) / delete a slot |
| GET / POST / PUT / DELETE | `/api/me/vehicles[/{id}]` | bookings.own | My vehicles |
| PUT | `/api/me/profile` | bookings.own | Name, phone, department |
| POST | `/api/bookings` | bookings.own | Book `{office_id, start_at, end_at, vehicle_id | visitor, slot_id?, prefer_ev, prefer_accessible, notes}` |
| GET | `/api/me/bookings?scope=upcoming|past|all` | bookings.own | My bookings (with QR payload) |
| GET | `/api/bookings/{id}` | bookings.own | One booking (own; security sees all) with `verdict` |
| PUT | `/api/bookings/{id}` | bookings.own | Change `{start_at, end_at}` (only the end once checked in) |
| POST | `/api/bookings/{id}/cancel` | bookings.own | Cancel `{reason}` (own; managers any) |
| POST | `/api/bookings/scan` | bookings.verify | Look up by QR text, booking code or vehicle number; returns `verdict` |
| POST | `/api/bookings/{id}/check-in`, `/check-out` | bookings.verify | Security check-in / check-out |
| GET | `/api/bookings?day=&office_id=&status=&q=` | bookings.verify | All bookings of a day, with status counts |
| GET | `/api/people?q=` | bookings.manage | Find people (assign slots) |

Booking errors come back as 400 (rule broken), 404 (not found / not yours) or 409 (slot taken, limit reached, wrong state) with a plain-language `detail`.

WebSocket event `booking` is sent on every booking change.

## WebSocket

`ws://<server>:8000/ws`. Within 10 seconds of connecting, send `{"type": "auth", "token": "<access token>"}` (the token is not put in the URL, where it would be logged). The server answers `{"type": "hello"}` or closes with code 4401. Send `"ping"` to receive `{"type":"pong"}`.

Every message has the form `{"type": "...", "data": {...}, "ts": "ISO-8601"}`.

| type | When | data |
|---|---|---|
| `detection` | A plate was recognised (any result) | detection object incl. status, plate, confidence, images |
| `entry` | Entry transaction created | entry transaction plus `session` |
| `exit` | Exit transaction created or resolved | exit transaction plus `session` (if matched) |
| `entry_updated` / `exit_updated` | Cancelled | transaction |
| `occupancy` | Occupancy changed | full occupancy snapshot |
| `camera_status` | Camera ONLINE / OFFLINE / CONNECTING / DISABLED | `{camera_id, name, status, error}` |
| `alert` / `alert_updated` | Alert created / resolved | alert |
| `session_updated` | Plate corrected | session |

## Roles

| Permission | Super Admin | Parking Manager | Security Operator | Report Viewer |
|---|:-:|:-:|:-:|:-:|
| Dashboard, reports, vehicle history, occupancy view, alerts view | ✓ | ✓ | ✓ | ✓ |
| View cameras / live video | ✓ | ✓ | ✓ | |
| Manual entry / exit, resolve unmatched exits, review detections, resolve alerts | ✓ | ✓ | ✓ | |
| Configure cameras, capacity, vehicle registry; cancel transactions; audit log | ✓ | ✓ | | |
| Users, system settings | ✓ | | | |
