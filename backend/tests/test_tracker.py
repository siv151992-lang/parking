"""Tracker: one event per physical vehicle, plate voting."""
import numpy as np

from app.anpr.tracker import Detection, VehicleTracker, point_in_polygon, vote_plate
from app.services.plates import is_valid_plate, normalize_plate, plate_distance

FRAME = np.zeros((540, 960, 3), np.uint8)


def drive(tracker, ys, plate="MH12AB1234", x=480, w=200, h=150):
    events = []
    for y in ys:
        d = Detection(bbox=(x - w / 2, y - h, x + w / 2, y), vehicle_type="CAR", confidence=0.9,
                      plate_text=plate, plate_confidence=0.9, plate_bbox=(int(x - 40), int(y - 40), int(x + 40), int(y - 20)))
        events += tracker.update([d], FRAME)
    for _ in range(20):
        events += tracker.update([], FRAME)
    return events


def test_vehicle_crossing_line_counts_once():
    t = VehicleTracker()
    ys = list(range(200, 530, 6))  # moves down through the trigger line (0.62*540=335)
    events = drive(t, ys)
    assert len(events) == 1
    assert events[0].plate_text == "MH12AB1234"
    assert events[0].trigger == "line"


def test_vehicle_waiting_at_barrier_counts_once():
    t = VehicleTracker()
    ys = list(range(200, 300, 5)) + [300] * 200 + list(range(300, 530, 5))  # stops for 200 frames
    events = drive(t, ys)
    assert len(events) == 1


def test_vehicle_outside_zone_not_counted():
    t = VehicleTracker()
    events = drive(t, [100] * 50)  # stays far away, above zone
    assert events == []


def test_two_vehicles_two_events():
    t = VehicleTracker()
    events = drive(t, list(range(200, 530, 8)), plate="MH12AB1234")
    events += drive(t, list(range(200, 530, 8)), plate="DL01CD5678")
    assert [e.plate_text for e in events] == ["MH12AB1234", "DL01CD5678"]


def test_vote_plate_majority():
    reads = [("MH12AB1234", 0.9), ("MH12A81234", 0.6), ("MH12AB1234", 0.85), ("MH12AB1Z34", 0.5)]
    text, conf = vote_plate(reads)
    assert text == "MH12AB1234" and 0 < conf <= 0.9


def test_vote_plate_per_character():
    reads = [("MH12AB1234", 0.8), ("MH12A81234", 0.8), ("MH12AB1Z34", 0.8), ("NH12AB1234", 0.8)]
    text, _ = vote_plate(reads)
    assert text == "MH12AB1234"


def test_point_in_polygon():
    poly = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon(5, 5, poly) and not point_in_polygon(15, 5, poly)


def test_plate_utils():
    assert normalize_plate(" mh-12 ab.1234 ") == "MH12AB1234"
    assert is_valid_plate("MH12AB1234") and not is_valid_plate("ABC") and not is_valid_plate("12345678")
    assert is_valid_plate("MH12AB1234", regex=r"[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}")
    assert not is_valid_plate("MH12AB12345", regex=r"[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}")
    assert plate_distance("MH12AB1234", "MH12A81234") == 0
    assert plate_distance("MH12AB1234", "MH12AB1235") == 1
