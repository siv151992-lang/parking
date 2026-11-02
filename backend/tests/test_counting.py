"""Vehicle counting logic: the most critical behaviour of the system."""
from datetime import timedelta

from app.models import (
    Alert,
    AlertType,
    DetectionStatus,
    ExitStatus,
    ParkingCapacity,
    ParkingSession,
    SessionStatus,
    Vehicle,
)
from app.services import counting
from app.services.counting import DetectionEvent, process_detection
from app.services.occupancy import reconcile, snapshot
from app.services.timeutil import utcnow


def ev(plate, conf=0.9, vtype="CAR", t=None, **kw):
    return DetectionEvent(plate_text=plate, plate_confidence=conf, vehicle_type=vtype, timestamp=t or utcnow(), **kw)


def inside(db):
    return snapshot(db)["occupied"]


def test_entry_creates_session_and_increments(db, cameras):
    r = process_detection(db, cameras["entry"], ev("MH12AB1234"))
    assert r["status"] == DetectionStatus.ENTRY_CREATED
    assert inside(db) == 1
    s = db.get(ParkingSession, r["session_id"])
    assert s.status == SessionStatus.ACTIVE and s.plate_number == "MH12AB1234" and s.category == "CAR"


def test_plate_normalisation(db, cameras):
    r = process_detection(db, cameras["entry"], ev("mh-12 ab 1234"))
    assert r["plate"] == "MH12AB1234"


def test_cooldown_blocks_repeat_reads_same_camera(db, cameras):
    t = utcnow()
    process_detection(db, cameras["entry"], ev("MH12AB1234", t=t))
    r = process_detection(db, cameras["entry"], ev("MH12AB1234", t=t + timedelta(seconds=20)))
    assert r["status"] == DetectionStatus.COOLDOWN
    assert inside(db) == 1


def test_cooldown_across_two_entry_cameras(db, cameras):
    t = utcnow()
    process_detection(db, cameras["entry"], ev("MH12AB1234", t=t))
    r = process_detection(db, cameras["entry2"], ev("MH12AB1234", t=t + timedelta(seconds=5)))
    assert r["status"] == DetectionStatus.COOLDOWN
    assert inside(db) == 1


def test_duplicate_entry_rejected_after_cooldown(db, cameras):
    t = utcnow()
    process_detection(db, cameras["entry"], ev("MH12AB1234", t=t))
    r = process_detection(db, cameras["entry"], ev("MH12AB1234", t=t + timedelta(minutes=5)))
    assert r["status"] == DetectionStatus.DUPLICATE
    assert inside(db) == 1
    assert db.query(Alert).filter(Alert.alert_type == AlertType.DUPLICATE_DETECTION).count() == 1


def test_reentry_after_missed_exit_auto_closes(db, cameras):
    t = utcnow() - timedelta(hours=3)
    process_detection(db, cameras["entry"], ev("MH12AB1234", t=t))
    r = process_detection(db, cameras["entry"], ev("MH12AB1234", t=t + timedelta(hours=2)))
    assert r["status"] == DetectionStatus.ENTRY_CREATED
    assert inside(db) == 1  # old session closed, new one opened
    assert db.query(ParkingSession).filter(ParkingSession.status == SessionStatus.CLOSED).count() == 1
    assert reconcile(db)["is_consistent"]


def test_exit_closes_session_and_decrements(db, cameras):
    t = utcnow() - timedelta(hours=1)
    process_detection(db, cameras["entry"], ev("MH12AB1234", t=t))
    r = process_detection(db, cameras["exit"], ev("MH12AB1234", t=t + timedelta(minutes=45)))
    assert r["status"] == DetectionStatus.EXIT_RECORDED and r["match"] == ExitStatus.MATCHED
    s = db.get(ParkingSession, r["session_id"])
    assert s.status == SessionStatus.CLOSED and s.duration_seconds == 45 * 60
    assert inside(db) == 0


def test_duplicate_exit_does_not_double_decrement(db, cameras):
    t = utcnow() - timedelta(hours=1)
    process_detection(db, cameras["entry"], ev("MH12AB1234", t=t))
    process_detection(db, cameras["entry"], ev("DL01CD5678", t=t + timedelta(minutes=1)))
    process_detection(db, cameras["exit"], ev("MH12AB1234", t=t + timedelta(minutes=30)))
    r = process_detection(db, cameras["exit"], ev("MH12AB1234", t=t + timedelta(minutes=30, seconds=10)))
    assert r["status"] == DetectionStatus.COOLDOWN
    r = process_detection(db, cameras["exit"], ev("MH12AB1234", t=t + timedelta(minutes=40)))
    assert r["status"] == "UNMATCHED"
    assert inside(db) == 1


def test_count_never_negative(db, cameras):
    r = process_detection(db, cameras["exit"], ev("KA01ZZ0001"))
    assert r["status"] == "UNMATCHED"
    assert inside(db) == 0
    assert db.query(Alert).filter(Alert.alert_type == AlertType.UNMATCHED_EXIT).count() == 1
    assert reconcile(db)["is_consistent"]


def test_fuzzy_exit_match_ocr_confusion(db, cameras):
    t = utcnow() - timedelta(hours=1)
    process_detection(db, cameras["entry"], ev("MH12AB1234", t=t))
    r = process_detection(db, cameras["exit"], ev("MH12A81234", t=t + timedelta(minutes=20)))  # B read as 8
    assert r["match"] == ExitStatus.FUZZY_MATCHED
    assert inside(db) == 0


def test_fuzzy_match_rejected_when_ambiguous(db, cameras):
    t = utcnow() - timedelta(hours=1)
    process_detection(db, cameras["entry"], ev("MH12AB1234", t=t))
    process_detection(db, cameras["entry"], ev("MH12AB1235", t=t + timedelta(minutes=1)))
    r = process_detection(db, cameras["exit"], ev("MH12AB1239", t=t + timedelta(minutes=20)))
    assert r["status"] == "UNMATCHED"
    assert inside(db) == 2


def test_unreadable_plate_still_counted_and_flagged(db, cameras):
    r = process_detection(db, cameras["entry"], ev(None, conf=0.0))
    assert r["status"] == DetectionStatus.ENTRY_CREATED
    assert inside(db) == 1
    s = db.get(ParkingSession, r["session_id"])
    assert s.plate_number is None and s.needs_review
    assert db.query(Alert).filter(Alert.alert_type == AlertType.OCR_FAILED).count() == 1


def test_low_confidence_treated_as_unread(db, cameras):
    r = process_detection(db, cameras["entry"], ev("MH12AB1234", conf=0.3))
    s = db.get(ParkingSession, r["session_id"])
    assert s.plate_number is None and s.needs_review


def test_unread_exit_matches_oldest_unread_session(db, cameras):
    t = utcnow() - timedelta(hours=2)
    process_detection(db, cameras["entry"], ev(None, conf=0, t=t))
    r = process_detection(db, cameras["exit"], ev(None, conf=0, t=t + timedelta(hours=1)))
    assert r["match"] == ExitStatus.UNREAD_MATCHED
    assert inside(db) == 0


def test_readable_exit_fills_plate_of_unread_session(db, cameras):
    t = utcnow() - timedelta(hours=2)
    r1 = process_detection(db, cameras["entry"], ev(None, conf=0, t=t))
    process_detection(db, cameras["exit"], ev("TN09XY4321", t=t + timedelta(hours=1)))
    s = db.get(ParkingSession, r1["session_id"])
    db.refresh(s)
    assert s.status == SessionStatus.CLOSED and s.plate_number == "TN09XY4321"


def test_vehicle_type_categories(db, cameras):
    process_detection(db, cameras["entry"], ev("MH01AA0001", vtype="TWO_WHEELER"))
    process_detection(db, cameras["entry"], ev("MH01AA0002", vtype="COMMERCIAL"))
    db.add(Vehicle(plate_number="MH01VIP001", is_reserved=True))
    db.commit()
    process_detection(db, cameras["entry"], ev("MH01VIP001"))
    cats = {c["category"]: c["occupied"] for c in snapshot(db)["categories"]}
    assert cats == {"CAR": 0, "TWO_WHEELER": 1, "HEAVY": 1, "RESERVED": 1}


def test_blacklisted_vehicle_alert(db, cameras):
    db.add(Vehicle(plate_number="UP32BL0001", is_blacklisted=True))
    db.commit()
    process_detection(db, cameras["entry"], ev("UP32BL0001"))
    assert db.query(Alert).filter(Alert.alert_type == AlertType.SUSPICIOUS_VEHICLE).count() == 1


def test_capacity_alerts_fire_once(db, cameras):
    cap = db.query(ParkingCapacity).filter(ParkingCapacity.category == "CAR").first()
    cap.total_capacity, cap.alert_threshold_pct = 4, 75
    db.commit()
    t = utcnow() - timedelta(hours=1)
    for i in range(5):
        process_detection(db, cameras["entry"], ev(f"MH12AB{1000 + i}", t=t + timedelta(minutes=i)))
    assert db.query(Alert).filter(Alert.alert_type == AlertType.CAPACITY_WARNING).count() == 1
    assert db.query(Alert).filter(Alert.alert_type == AlertType.CAPACITY_FULL).count() == 1
    car = next(c for c in snapshot(db)["categories"] if c["category"] == "CAR")
    assert car["available"] == 0 and car["occupied"] == 5  # over capacity is still counted


def test_manual_entry_exit_and_audit(db, cameras, admin):
    counting.manual_entry(db, admin, "KA05MN7777", "CAR", None, notes="barrier fault")
    assert inside(db) == 1
    counting.manual_exit(db, admin, plate_text="KA05MN7777")
    assert inside(db) == 0
    from app.models import AuditLog
    assert {a.action for a in db.query(AuditLog)} >= {"MANUAL_ENTRY", "MANUAL_EXIT"}


def test_manual_entry_duplicate_rejected(db, cameras, admin):
    counting.manual_entry(db, admin, "KA05MN7777", "CAR", None)
    try:
        counting.manual_entry(db, admin, "KA05MN7777", "CAR", None)
        assert False, "expected CountingError"
    except counting.CountingError as e:
        assert e.status_code == 409


def test_cancel_entry_removes_from_count(db, cameras, admin):
    r = process_detection(db, cameras["entry"], ev("MH12AB1234"))
    counting.cancel_entry(db, admin, r["transaction_id"], "false detection - shadow")
    assert inside(db) == 0
    assert reconcile(db)["is_consistent"]


def test_cancel_exit_reopens_session(db, cameras, admin):
    t = utcnow() - timedelta(hours=1)
    process_detection(db, cameras["entry"], ev("MH12AB1234", t=t))
    r = process_detection(db, cameras["exit"], ev("MH12AB1234", t=t + timedelta(minutes=10)))
    counting.cancel_exit(db, admin, r["transaction_id"], "wrong vehicle")
    assert inside(db) == 1
    assert reconcile(db)["is_consistent"]


def test_resolve_unmatched_exit(db, cameras, admin):
    t = utcnow() - timedelta(hours=1)
    e = process_detection(db, cameras["entry"], ev("MH12AB1234", t=t))
    x = process_detection(db, cameras["exit"], ev("ZZ99ZZ9999", t=t + timedelta(minutes=30)))
    assert inside(db) == 1
    counting.resolve_unmatched_exit(db, admin, x["transaction_id"], e["session_id"])
    assert inside(db) == 0
    assert reconcile(db)["is_consistent"]
    assert db.query(Alert).filter(Alert.alert_type == AlertType.UNMATCHED_EXIT, Alert.is_resolved.is_(False)).count() == 0


def test_review_detection_corrects_session_plate(db, cameras, admin):
    r = process_detection(db, cameras["entry"], ev(None, conf=0))
    counting.review_detection(db, admin, r["detection_id"], "GJ01AB0001", None)
    s = db.get(ParkingSession, r["session_id"])
    db.refresh(s)
    assert s.plate_number == "GJ01AB0001" and not s.needs_review
    # now the readable exit matches exactly
    x = process_detection(db, cameras["exit"], ev("GJ01AB0001"))
    assert x["match"] == ExitStatus.MATCHED


def test_reconciliation_after_mixed_traffic(db, cameras, admin):
    import random
    rng = random.Random(7)
    t = utcnow() - timedelta(hours=10)
    plates = [f"MH{i:02d}AB{i * 37 % 9999:04d}" for i in range(1, 40)]
    inside_set = set()
    for i in range(300):
        t += timedelta(minutes=2)
        p = rng.choice(plates)
        cam = cameras["exit"] if p in inside_set and rng.random() < 0.6 else cameras["entry"]
        process_detection(db, cam, ev(p if rng.random() > 0.05 else None, conf=rng.uniform(0.5, 0.99), t=t))
        if cam == cameras["entry"]:
            inside_set.add(p)
        else:
            inside_set.discard(p)
    rec = reconcile(db)
    assert rec["is_consistent"], rec
    assert inside(db) >= 0
