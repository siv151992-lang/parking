"""Office parking: offices, slots, employee reservations, visitors, security check-in / out."""
from datetime import datetime, time, timedelta, timezone

import pytest

from app.models import BookingStatus, SlotBooking, User
from app.security import hash_password
from app.services import bookings as svc
from app.services import settings_store
from app.services.timeutil import utcnow

from .conftest import login

PW = "Employee-pw1"


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def tomorrow_at(hour, minute=0):
    """Tomorrow at a local (Asia/Kolkata) time, inside office hours."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Kolkata")
    d = datetime.now(tz).date() + timedelta(days=1)
    return datetime.combine(d, time(hour, minute), tzinfo=tz)


@pytest.fixture
def office(client):
    """HQ: Basement 1 / zone A with 3 car slots (A-01 EV, A-02, A-03 accessible), 1 visitor slot, 1 bike slot."""
    h = login(client)
    o = client.post("/api/offices", headers=h, json={"name": "HQ", "city": "Bengaluru", "latitude": 12.97, "longitude": 77.59,
                                                     "open_time": "07:00", "close_time": "22:00"}).json()
    o = client.post(f"/api/offices/{o['id']}/floors", headers=h, json={"name": "Basement 1", "level": -1}).json()
    fid = o["floors"][0]["id"]
    o = client.post(f"/api/floors/{fid}/zones", headers=h, json={"name": "A"}).json()
    zid = o["floors"][0]["zones"][0]["id"]
    assert client.post(f"/api/zones/{zid}/slots", headers=h, json={"prefix": "A-", "start": 1, "count": 1, "is_ev": True}).status_code == 201
    client.post(f"/api/zones/{zid}/slots", headers=h, json={"prefix": "A-", "start": 2, "count": 1})
    client.post(f"/api/zones/{zid}/slots", headers=h, json={"prefix": "A-", "start": 3, "count": 1, "is_accessible": True})
    client.post(f"/api/zones/{zid}/slots", headers=h, json={"prefix": "V-", "start": 1, "count": 1, "is_visitor": True})
    client.post(f"/api/zones/{zid}/slots", headers=h, json={"prefix": "B-", "start": 1, "count": 1, "vehicle_type": "TWO_WHEELER"})
    slots = {s["code"]: s for s in client.get(f"/api/offices/{o['id']}/slots", headers=h).json()}
    return {"id": o["id"], "zone": zid, "slots": slots, "admin": h}


def employee(client, db, name="asha", vehicle="KA01AB1234"):
    db.add(User(username=name, email=f"{name}@corp.com", full_name=name.title(), role="EMPLOYEE",
                hashed_password=hash_password(PW)))
    db.commit()
    h = login(client, name, PW)
    v = client.post("/api/me/vehicles", headers=h, json={"plate_number": vehicle, "vehicle_type": "CAR"})
    assert v.status_code == 201, v.text
    return h, v.json()["id"]


def book(client, h, office_id, vid=None, start=None, end=None, **kw):
    start = start or tomorrow_at(9)
    end = end or tomorrow_at(18)
    return client.post("/api/bookings", headers=h, json={"office_id": office_id, "vehicle_id": vid,
                                                         "start_at": iso(start), "end_at": iso(end), **kw})


def test_slot_setup_and_duplicates(client, office):
    h = office["admin"]
    assert len(office["slots"]) == 5 and office["slots"]["B-01"]["vehicle_type"] == "TWO_WHEELER"
    r = client.post(f"/api/zones/{office['zone']}/slots", headers=h, json={"prefix": "A-", "start": 1, "count": 3})
    assert r.status_code == 409 and "A-01" in r.text
    assert client.post("/api/offices", headers=h, json={"name": "hq"}).status_code == 409


def test_booking_auto_allocation_and_no_double_booking(client, db, office):
    h1, v1 = employee(client, db, "asha", "KA01AB1234")
    h2, v2 = employee(client, db, "ravi", "KA02CD5678")
    h3, v3 = employee(client, db, "mona", "KA03EF9012")
    r = book(client, h1, office["id"], v1)
    assert r.status_code == 201, r.text
    b1 = r.json()
    # auto allocation keeps the EV charger and the accessible slot for people who need them
    assert b1["slot_code"] == "A-02" and b1["qr"].startswith("OPB1:" + b1["code"] + ":")
    b2 = book(client, h2, office["id"], v2).json()
    b3 = book(client, h3, office["id"], v3, prefer_ev=True).json()
    assert b3["slot_code"] == "A-01"
    assert b2["slot_code"] in ("A-01", "A-03")
    # asking for the slot someone already has: refused
    r = book(client, h3, office["id"], v3, start=tomorrow_at(19), end=tomorrow_at(20), slot_id=office["slots"]["A-02"]["id"])
    assert r.status_code == 409 and "per day" in r.text  # mona already has a booking that day
    db.execute(SlotBooking.__table__.update().values(status="CANCELLED").where(SlotBooking.id == b3["id"]))
    db.commit()
    r = book(client, h3, office["id"], v3, start=tomorrow_at(10), end=tomorrow_at(11), slot_id=office["slots"]["A-02"]["id"])
    assert r.status_code == 409 and "already booked" in r.text
    # the visitor-only slot is not used for employees, and the bike slot does not fit a car: office full for cars
    h4, v4 = employee(client, db, "joe", "KA04GH3456")
    book(client, h4, office["id"], v4)  # takes the freed EV slot
    h5, v5 = employee(client, db, "kim", "KA05JK7890")
    r = book(client, h5, office["id"], v5)
    assert r.status_code == 409 and "No free slot" in r.text
    # adjacent bookings are fine: [9,18) then [18,20)
    r = book(client, h5, office["id"], v5, start=tomorrow_at(18), end=tomorrow_at(20), slot_id=office["slots"]["A-02"]["id"])
    assert r.status_code == 201, r.text


def test_booking_rules(client, db, office):
    h, v = employee(client, db)
    oid = office["id"]
    assert "past" in book(client, h, oid, v, start=utcnow() - timedelta(hours=2), end=utcnow() + timedelta(hours=1)).text
    assert "after the start" in book(client, h, oid, v, start=tomorrow_at(10), end=tomorrow_at(9)).text
    assert "at least 30 minutes" in book(client, h, oid, v, start=tomorrow_at(10), end=tomorrow_at(10, 10)).text
    assert "open 07:00-22:00" in book(client, h, oid, v, start=tomorrow_at(6), end=tomorrow_at(9)).text
    far = tomorrow_at(9) + timedelta(days=30)
    assert "days ahead" in book(client, h, oid, v, start=far, end=far + timedelta(hours=8)).text
    assert "registered vehicles" in book(client, h, oid, 99999).text
    r = book(client, h, oid, v)
    assert r.status_code == 201
    assert "per day" in book(client, h, oid, v, start=tomorrow_at(19), end=tomorrow_at(21)).text
    # the same vehicle cannot hold two bookings at once, even through another office
    h2 = office["admin"]
    o2 = client.post("/api/offices", headers=h2, json={"name": "Annex", "is_24h": True}).json()
    o2 = client.post(f"/api/offices/{o2['id']}/floors", headers=h2, json={"name": "G"}).json()
    o2 = client.post(f"/api/floors/{o2['floors'][0]['id']}/zones", headers=h2, json={"name": "Z"}).json()
    client.post(f"/api/zones/{o2['floors'][0]['zones'][0]['id']}/slots", headers=h2, json={"prefix": "Z", "count": 2})
    settings_store.update(db, {"booking_max_per_day": 3}); db.commit(); settings_store.invalidate()
    assert "already has a booking" in book(client, h, o2["id"], v, start=tomorrow_at(12), end=tomorrow_at(13)).text


def test_visitor_and_assigned_slots(client, db, office):
    h, v = employee(client, db)
    r = book(client, h, office["id"], visitor={"name": "Mr Rao", "plate_number": "TN09XY1111"})
    assert r.status_code == 201, r.text
    assert r.json()["slot_code"] == "V-01" and r.json()["visitor_name"] == "Mr Rao"
    # visitor bookings do not count towards the employee's daily limit
    assert book(client, h, office["id"], v).status_code == 201
    # a slot assigned to someone else is not bookable
    admin = office["admin"]
    ravi = User(username="ravi", email="ravi@corp.com", role="EMPLOYEE", hashed_password=hash_password(PW))
    db.add(ravi); db.commit()
    a3 = office["slots"]["A-03"]["id"]
    assert client.put(f"/api/slots/{a3}", headers=admin, json={"assigned_user_id": ravi.id}).status_code == 200
    h2, v2 = employee(client, db, "mona", "KA03EF9012")
    r = book(client, h2, office["id"], v2, start=tomorrow_at(12), end=tomorrow_at(13), slot_id=a3)
    assert r.status_code == 409 and "assigned to another" in r.text
    # ...but its owner gets it automatically
    hr = login(client, "ravi", PW)
    vr = client.post("/api/me/vehicles", headers=hr, json={"plate_number": "KA09ZZ0001"}).json()["id"]
    assert book(client, hr, office["id"], vr, start=tomorrow_at(12), end=tomorrow_at(13)).json()["slot_code"] == "A-03"


def test_change_cancel_and_permissions(client, db, office):
    h, v = employee(client, db)
    b = book(client, h, office["id"], v).json()
    r = client.put(f"/api/bookings/{b['id']}", headers=h, json={"start_at": iso(tomorrow_at(10)), "end_at": iso(tomorrow_at(19))})
    assert r.status_code == 200 and r.json()["end_at"].startswith(iso(tomorrow_at(19))[:16])
    h2, _ = employee(client, db, "ravi", "KA02CD5678")
    assert client.get(f"/api/bookings/{b['id']}", headers=h2).status_code == 404           # not someone else's
    assert client.post(f"/api/bookings/{b['id']}/cancel", headers=h2, json={}).status_code == 404
    assert client.get("/api/bookings", headers=h2).status_code == 403                       # no security console
    assert client.get("/api/dashboard/stats", headers=h2).status_code == 403                 # no staff console
    assert client.post(f"/api/bookings/{b['id']}/cancel", headers=h, json={"reason": "WFH"}).json()["status"] == "CANCELLED"
    assert client.post(f"/api/bookings/{b['id']}/cancel", headers=h, json={}).status_code == 409
    assert client.get("/api/me/bookings?scope=past", headers=h).json()["total"] == 1


def test_scan_check_in_out_and_no_show(client, db, office):
    h, v = employee(client, db)
    start = utcnow() + timedelta(minutes=10)
    from zoneinfo import ZoneInfo
    local = start.astimezone(ZoneInfo("Asia/Kolkata"))
    if not (time(7) <= local.time() <= time(20, 30)):
        db.query(type(db.get(User, 1))).first()  # outside office hours: use the 24h annex
        office_id = client.post("/api/offices", headers=office["admin"], json={"name": "Night", "is_24h": True}).json()["id"]
        o = client.post(f"/api/offices/{office_id}/floors", headers=office["admin"], json={"name": "G"}).json()
        o = client.post(f"/api/floors/{o['floors'][0]['id']}/zones", headers=office["admin"], json={"name": "Z"}).json()
        client.post(f"/api/zones/{o['floors'][0]['zones'][0]['id']}/slots", headers=office["admin"], json={"prefix": "N", "count": 1})
    else:
        office_id = office["id"]
    b = book(client, h, office_id, v, start=start, end=start + timedelta(hours=1)).json()
    guard = office["admin"]
    r = client.post("/api/bookings/scan", headers=guard, json={"text": b["qr"]})
    assert r.status_code == 200 and r.json()["verdict"]["action"] == "CHECK_IN"
    forged = b["qr"].rsplit(":", 1)[0] + ":forged"
    assert client.post("/api/bookings/scan", headers=guard, json={"text": forged}).status_code == 404
    assert client.post("/api/bookings/scan", headers=guard, json={"text": "ka01ab1234"}).json()["code"] == b["code"]
    assert client.post(f"/api/bookings/{b['id']}/check-in", headers=guard).json()["status"] == "CHECKED_IN"
    assert client.post(f"/api/bookings/{b['id']}/cancel", headers=h, json={}).status_code == 409   # parked: cannot cancel
    assert client.post(f"/api/bookings/{b['id']}/check-out", headers=guard).json()["status"] == "COMPLETED"
    assert client.post(f"/api/bookings/{b['id']}/check-out", headers=guard).status_code == 409
    # no-show: a booking that started 2 hours ago and was never checked in is released
    late = SlotBooking(code="LATE0001", qr_token="t", user_id=1, office_id=office["id"], slot_id=office["slots"]["A-02"]["id"],
                       slot_code="A-02", plate_number="X1", start_at=utcnow() - timedelta(hours=2),
                       end_at=utcnow() + timedelta(hours=2), status=BookingStatus.CONFIRMED)
    db.add(late); db.commit()
    assert svc.sweep(db)["released"] == 1
    db.refresh(late)
    assert late.status == BookingStatus.NO_SHOW


def test_availability_and_office_list(client, db, office):
    h, v = employee(client, db)
    book(client, h, office["id"], v)
    s, e = iso(tomorrow_at(12)), iso(tomorrow_at(13))
    lst = client.get("/api/offices", params={"start": s, "end": e}, headers=h).json()
    hq = next(o for o in lst if o["name"] == "HQ")
    assert hq["slots_total"] == 5 and hq["slots_free"] == 3 and hq["visitor_free"] == 1  # 4 non-visitor slots, 1 mine
    av = client.get(f"/api/offices/{office['id']}/availability", params={"start": s, "end": e}, headers=h).json()
    states = {x["code"]: x["state"] for x in av["slots"]}
    assert states["A-02"] == "MINE" and states["A-01"] == "AVAILABLE"
    assert "booking" not in next(x for x in av["slots"] if x["code"] == "A-02")      # employees do not see details
    guard_view = client.get(f"/api/offices/{office['id']}/availability", params={"start": s, "end": e},
                            headers=office["admin"]).json()
    assert next(x for x in guard_view["slots"] if x["code"] == "A-02")["booking"]["plate_number"] == "KA01AB1234"


def test_vehicle_ownership(client, db, office):
    h, v = employee(client, db)
    h2 = login(client, *(lambda: (employee(client, db, "ravi", "KA02CD5678"), ("ravi", PW))[1])())
    r = client.post("/api/me/vehicles", headers=h2, json={"plate_number": "ka-01 ab 1234"})
    assert r.status_code == 409 and "another person" in r.text
    book(client, h, office["id"], v)
    assert client.delete(f"/api/me/vehicles/{v}", headers=h).status_code == 409   # has an upcoming booking


def test_self_registration(client, db):
    body = {"full_name": "New Person", "email": "new@corp.com", "password": "Str0ng-pass"}
    assert client.post("/api/auth/register", json=body).status_code == 403            # switched off by default
    settings_store.update(db, {"employee_signup_domains": "corp.com, corp.in"}); db.commit(); settings_store.invalidate()
    assert client.get("/api/auth/signup-info").json() == {"enabled": True, "domains": ["corp.com", "corp.in"]}
    r = client.post("/api/auth/register", json={**body, "email": "x@gmail.com"})
    assert r.status_code == 403 and "@corp.com" in r.text
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 201 and r.json()["user"]["role"] == "EMPLOYEE"
    assert client.post("/api/auth/register", json=body).status_code == 409
    tok = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/me/vehicles", headers=tok).status_code == 200
    assert client.get("/api/cameras", headers=tok).status_code == 403


def test_postgres_rejects_overlapping_bookings(client, db, office):
    """The database itself refuses two overlapping holding bookings on a slot (PostgreSQL only)."""
    if db.bind.dialect.name != "postgresql":
        pytest.skip("exclusion constraint is PostgreSQL only")
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    exists = db.execute(text("SELECT 1 FROM pg_constraint WHERE conname = 'ex_booking_no_overlap'")).first()
    if not exists:
        pytest.skip("tables created without migrations")
    slot = office["slots"]["A-02"]["id"]
    s = utcnow() + timedelta(days=1)
    db.add(SlotBooking(code="PG000001", qr_token="t", user_id=1, office_id=office["id"], slot_id=slot, slot_code="A-02",
                       start_at=s, end_at=s + timedelta(hours=2), status="CONFIRMED"))
    db.commit()
    db.add(SlotBooking(code="PG000002", qr_token="t", user_id=1, office_id=office["id"], slot_id=slot, slot_code="A-02",
                       start_at=s + timedelta(hours=1), end_at=s + timedelta(hours=3), status="CONFIRMED"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
