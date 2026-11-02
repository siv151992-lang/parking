# Testing

## Automated tests (45 tests)

```bash
cd backend
.venv/bin/pytest -q                       # throw-away SQLite database
TEST_DATABASE_URL=postgresql+psycopg2://parking:parking@localhost/smart_parking_test .venv/bin/pytest -q   # PostgreSQL
```

The PostgreSQL run is recommended before every deployment, because it exercises the partial unique index and `SELECT … FOR UPDATE`. Create the database first with `CREATE DATABASE smart_parking_test OWNER parking;`.

| File | Covers |
|---|---|
| `tests/test_counting.py` | Entry / exit, cooldown on one camera and across two entry cameras, duplicate entry, duplicate exit, never-negative count, fuzzy OCR matching (and rejection when ambiguous), unreadable plates, low confidence, unread-session matching, categories / reserved, blacklist alerts, capacity alerts firing once, manual entry / exit, cancel entry / exit, resolve unmatched exit, detection review, reconciliation after 300 mixed random events |
| `tests/test_tracker.py` | One event per vehicle crossing the line, one event for a vehicle waiting 200 frames at a barrier, no event outside the zone, two vehicles → two events, plate voting (whole string and per character), plate utilities |
| `tests/test_api.py` | Login, lockout, auth required, RBAC per role, camera CRUD + inject, manual flow + history, capacity, all 10 reports × CSV / XLSX / PDF, settings validation, audit log, user management, WebSocket events, WebSocket auth |

## Manual end-to-end test with simulated cameras

1. `python -m app.seed --days 14` creates 3 simulated cameras (2 entry, 1 exit), 1 disabled real-camera template, 4 users, and 14 days of history.
2. Start the backend and open the UI. Within a minute **Live Camera Monitoring** shows vehicles driving through the zone. Each vehicle box turns green with **COUNTED** exactly once, even when it waits at the barrier.
3. Watch **Dashboard**: *Total Entry*, *Vehicles Inside* and *Recent detections* update without refreshing.
4. **Duplicate test**: *Inject test vehicle* → entry camera, plate `TEST1234AB`. Inject it again immediately → result `COOLDOWN`. Inject it again on the second entry camera → `COOLDOWN` (the cooldown spans cameras). After the cooldown (60 s) → `DUPLICATE` plus a *Duplicate entry blocked* alert. *Vehicles Inside* went up by only 1.
5. **Exit test**: inject `TEST1234AB` on the exit camera → `EXIT_RECORDED / MATCHED`, and inside goes down by 1. Inject it again after 60 s → `UNMATCHED`, with an *Unmatched vehicle exit* alert, and the count is unchanged.
6. **OCR confusion**: enter `MH12AB1234`, then exit `MH12A81234` → `FUZZY_MATCHED`, and the session is flagged for review.
7. **Failed read**: inject with an empty plate on entry → counted, *Number plate recognition failed* alert, and the item appears in **Vehicle History → Review queue**. Correct it there and the session gets the plate.
8. **Unmatched resolution**: **Vehicle Exit → Show unmatched only → Resolve** → link to the suggested session. The count drops by 1 and the alert is resolved.
9. **Capacity alert**: **Parking Occupancy → Car Parking → Configure**, set capacity just above the current occupancy. A warning and then a FULL alert appear in the bell and as toasts.
10. **Camera failure**: edit a real camera with a wrong URL, or set `SIM_DISCONNECT_PROBABILITY=2` and restart. The camera turns OFFLINE, shows *Camera disconnected*, reconnects with back-off, then shows *Camera connection restored*.
11. **Reconciliation**: **Parking Occupancy** shows `entries − exits = active sessions`, so the counts are consistent.
12. **Reports**: every report type is shown on screen and exported to CSV, Excel and PDF. *Data source → Real cameras only* excludes simulated data.
13. **RBAC**: log in as `viewer / Viewer@123`. Cameras, users and settings are hidden, and the API returns 403.

## Testing with real footage but no camera

Add a *real* camera whose RTSP URL is a local video path (for example `/data/gate_entry.mp4`). The file loops at its native FPS through the full YOLO + PaddleOCR pipeline. This needs `requirements-ai.txt`. You can also serve a file as RTSP with [mediamtx](https://github.com/bluenviron/mediamtx):
`ffmpeg -re -stream_loop -1 -i gate.mp4 -c copy -f rtsp rtsp://localhost:8554/gate`.
