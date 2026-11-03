"""Row-by-row free spaces with a camera at each row entrance."""
from datetime import timedelta

import pytest

from app.models import Camera, DetectionStatus, Direction, ParkingRow
from app.services.counting import DetectionEvent, process_detection
from app.services.occupancy import snapshot
from app.services.timeutil import utcnow

from .conftest import login


def ev(plate, conf=0.9, t=None):
    return DetectionEvent(plate_text=plate, plate_confidence=conf, timestamp=t or utcnow())


@pytest.fixture
def rows(db, cameras):
    a, b = ParkingRow(name="Row A", capacity=3, sort_order=1), ParkingRow(name="Row B", capacity=2, sort_order=2)
    db.add_all([a, b])
    db.flush()
    cams = {}
    for row in (a, b):
        for d in (Direction.ENTRY, Direction.EXIT):
            c = Camera(camera_code=f"{row.name}-{d}", name=f"{row.name} {d}", direction=d, is_simulated=True,
                       cooldown_seconds=60, min_plate_confidence=0.6, row_id=row.id)
            db.add(c)
            db.flush()
            cams[(row.name[-1], d)] = c.id
    db.commit()
    return {"A": a.id, "B": b.id, **cameras, "cams": cams}


def row(db, name):
    db.expire_all()
    return next(r for r in snapshot(db)["rows"] if r["name"] == f"Row {name}")


def test_row_entry_and_exit_change_only_the_row(db, rows):
    c = rows["cams"]
    process_detection(db, rows["entry"], ev("MH12AB1234"))           # main gate
    assert snapshot(db)["occupied"] == 1 and row(db, "A")["occupied"] == 0
    r = process_detection(db, c[("A", "ENTRY")], ev("MH12AB1234"))
    assert r["status"] == DetectionStatus.ROW_ENTRY
    assert row(db, "A")["occupied"] == 1 and row(db, "A")["available"] == 2
    assert snapshot(db)["occupied"] == 1                              # car park total unchanged
    r = process_detection(db, c[("A", "EXIT")], ev("MH12AB1234"))
    assert r["status"] == DetectionStatus.ROW_EXIT
    assert row(db, "A")["occupied"] == 0 and snapshot(db)["occupied"] == 1


def test_duplicate_row_entry_is_ignored(db, rows):
    cam = rows["cams"][("A", "ENTRY")]
    t = utcnow()
    process_detection(db, cam, ev("KA01AB1234", t=t))
    assert process_detection(db, cam, ev("KA01AB1234", t=t + timedelta(seconds=5)))["status"] == DetectionStatus.ROW_IGNORED
    assert process_detection(db, cam, ev("KA01AB1234", t=t + timedelta(minutes=5)))["status"] == DetectionStatus.ROW_IGNORED
    assert row(db, "A")["occupied"] == 1


def test_row_count_never_negative(db, rows):
    cam = rows["cams"][("B", "EXIT")]
    assert process_detection(db, cam, ev("DL01AB1111"))["status"] == DetectionStatus.ROW_IGNORED
    assert process_detection(db, cam, ev(""))["status"] == DetectionStatus.ROW_IGNORED
    assert row(db, "B")["occupied"] == 0


def test_moving_between_rows(db, rows):
    c = rows["cams"]
    process_detection(db, c[("A", "ENTRY")], ev("TN09CD4321"))
    process_detection(db, c[("B", "ENTRY")], ev("TN09CD4321"))       # missed Row A's exit camera
    assert row(db, "A")["occupied"] == 0 and row(db, "B")["occupied"] == 1


def test_gate_exit_frees_the_row_space(db, rows):
    c = rows["cams"]
    process_detection(db, rows["entry"], ev("GJ05EF5555"))
    process_detection(db, c[("A", "ENTRY")], ev("GJ05EF5555"))
    assert row(db, "A")["occupied"] == 1
    process_detection(db, rows["exit"], ev("GJ05EF5555"))             # left through the main gate
    assert row(db, "A")["occupied"] == 0


def test_unread_plates_and_fuzzy_row_exit(db, rows):
    c = rows["cams"]
    process_detection(db, c[("A", "ENTRY")], ev(""))                  # unreadable, still takes a space
    process_detection(db, c[("A", "ENTRY")], ev("MH12AB1234"))
    assert row(db, "A")["occupied"] == 2
    r = process_detection(db, c[("A", "EXIT")], ev("MH12A81234"))     # OCR read 8 for B
    assert r["status"] == DetectionStatus.ROW_EXIT and r["match"] == "FUZZY"
    r = process_detection(db, c[("A", "EXIT")], ev("", conf=0.1))      # unreadable exit frees the unread one
    assert r["status"] == DetectionStatus.ROW_EXIT
    assert row(db, "A")["occupied"] == 0


def test_row_full_alert(db, rows):
    from app.models import Alert, AlertType
    cam = rows["cams"][("B", "ENTRY")]
    process_detection(db, cam, ev("KA01AA0001"))
    process_detection(db, cam, ev("KA01AA0002"))
    assert row(db, "B")["available"] == 0
    full = db.query(Alert).filter(Alert.alert_type == AlertType.CAPACITY_FULL).all()
    assert [a.title for a in full] == ["Row B is FULL"]


def test_rows_api(client, db):
    h = login(client)
    r = client.post("/api/rows", json={"name": "Row C", "capacity": 10}, headers=h)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert client.post("/api/rows", json={"name": "Row C", "capacity": 5}, headers=h).status_code == 409
    cam = client.post("/api/cameras", json={"name": "C in", "direction": "ENTRY", "is_simulated": True, "is_enabled": False,
                                            "row_id": rid}, headers=h)
    assert cam.status_code == 201, cam.text
    assert cam.json()["camera_code"] == "CAM-ROWC-EN-01" and cam.json()["row_id"] == rid
    gate = client.post("/api/cameras", json={"name": "Gate", "direction": "EXIT", "is_simulated": True, "is_enabled": False}, headers=h)
    assert gate.json()["camera_code"] == "CAM-EX-01"
    r = client.post(f"/api/rows/{rid}/count", json={"count": 4, "reason": "camera was down"}, headers=h)
    assert r.json()["occupied"] == 4 and r.json()["available"] == 6
    r = client.post(f"/api/rows/{rid}/count", json={"count": 1}, headers=h)
    assert r.json()["occupied"] == 1
    assert len(client.get(f"/api/rows/{rid}/vehicles", headers=h).json()) == 1
    assert client.put(f"/api/rows/{rid}", json={"capacity": 12}, headers=h).json()["available"] == 11
    assert any(x["name"] == "Row C" for x in client.get("/api/occupancy", headers=h).json()["rows"])
    assert client.delete(f"/api/rows/{rid}", headers=h).status_code == 204
    assert client.get(f"/api/cameras/{cam.json()['id']}", headers=h).json()["row_id"] is None
