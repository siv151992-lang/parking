"""Reports & analytics. Every report returns a common structure

    {title, subtitle, columns: [{key, label}], rows: [...], summary: {...}, chart: {...}}

which the UI renders and the exporters turn into CSV / Excel / PDF.
"""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..models import (
    Camera,
    DetectionStatus,
    EntryStatus,
    EntryTransaction,
    ExitStatus,
    ExitTransaction,
    ParkingSession,
    SessionStatus,
    VehicleDetection,
)
from . import settings_store
from .occupancy import snapshot
from .timeutil import facility_tz, range_bounds

REPORT_TYPES = {
    "daily_entry": "Daily Vehicle Entry Report",
    "daily_exit": "Daily Vehicle Exit Report",
    "hourly": "Hourly Vehicle Traffic Report",
    "weekly": "Weekly Vehicle Report",
    "monthly": "Monthly Vehicle Report",
    "category": "Vehicle Category Report",
    "camera": "Camera-wise Detection Report",
    "occupancy": "Current Occupancy Report",
    "peak_hours": "Peak-Hour Traffic Analysis",
    "accuracy": "ANPR Recognition Accuracy Report",
}


def _fmt_dt(dt: datetime | None, tz) -> str:
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def _fmt_dur(sec: int | float | None) -> str:
    if sec is None:
        return ""
    sec = int(sec)
    return f"{sec // 3600}h {sec % 3600 // 60:02d}m"


def _entries(db, s, e, include_sim=True):
    q = db.query(EntryTransaction).filter(EntryTransaction.timestamp >= s, EntryTransaction.timestamp < e,
                                          EntryTransaction.status == EntryStatus.VALID)
    if not include_sim:
        q = q.filter(EntryTransaction.source != "SIMULATED")
    return q.order_by(EntryTransaction.timestamp).all()


def _exits(db, s, e, include_sim=True, counted_only=True):
    q = db.query(ExitTransaction).filter(ExitTransaction.timestamp >= s, ExitTransaction.timestamp < e)
    q = q.filter(ExitTransaction.status.in_(ExitStatus.COUNTED)) if counted_only else q.filter(ExitTransaction.status != ExitStatus.CANCELLED)
    if not include_sim:
        q = q.filter(ExitTransaction.source != "SIMULATED")
    return q.order_by(ExitTransaction.timestamp).all()


def _durations(db, s, e, include_sim):
    q = db.query(ParkingSession).filter(ParkingSession.exit_time >= s, ParkingSession.exit_time < e,
                                        ParkingSession.status == SessionStatus.CLOSED)
    if not include_sim:
        q = q.filter(ParkingSession.is_simulated.is_(False))
    return q.all()


def build_report(db: Session, rtype: str, start: date, end: date, include_simulated: bool = True) -> dict:
    if rtype not in REPORT_TYPES:
        raise ValueError(f"Unknown report type {rtype}")
    tz = facility_tz(db)
    if rtype in ("daily_entry", "daily_exit", "hourly"):
        end = start
    if rtype == "monthly":
        start = start.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    s, e = range_bounds(db, start, end)
    sim = include_simulated
    builder = globals()[f"_r_{rtype}"]
    rep = builder(db, s, e, start, end, tz, sim)
    rep["type"] = rtype
    rep["title"] = REPORT_TYPES[rtype]
    rep["facility"] = settings_store.get(db, "facility_name")
    rep["period"] = {"start": start.isoformat(), "end": end.isoformat()}
    rep.setdefault("subtitle", f"{start:%d %b %Y}" + (f" - {end:%d %b %Y}" if end != start else ""))
    rep["include_simulated"] = sim
    rep["generated_at"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    return rep


# ----------------------------------------------------------------- builders
def _r_daily_entry(db, s, e, start, end, tz, sim):
    rows = [
        {"time": _fmt_dt(t.timestamp, tz), "plate": t.plate_number or "UNREAD", "vehicle_type": t.vehicle_type,
         "category": t.category, "camera": t.camera.name if t.camera else "Manual", "confidence": round(t.confidence * 100, 1),
         "source": t.source}
        for t in _entries(db, s, e, sim)
    ]
    by_type = Counter(r["vehicle_type"] for r in rows)
    return {
        "columns": [{"key": "time", "label": "Entry Time"}, {"key": "plate", "label": "Registration No."},
                    {"key": "vehicle_type", "label": "Vehicle Type"}, {"key": "category", "label": "Parking Category"},
                    {"key": "camera", "label": "Camera"}, {"key": "confidence", "label": "Confidence %"},
                    {"key": "source", "label": "Source"}],
        "rows": rows,
        "summary": {"Total entries": len(rows), **{f"{k} entries": v for k, v in by_type.items()}},
        "chart": {"kind": "pie", "data": [{"name": k, "value": v} for k, v in by_type.items()]},
    }


def _r_daily_exit(db, s, e, start, end, tz, sim):
    exits = _exits(db, s, e, sim, counted_only=False)
    sessions = {x.id: x for x in db.query(ParkingSession).filter(ParkingSession.id.in_([t.session_id for t in exits if t.session_id])).all()} if exits else {}
    rows = []
    for t in exits:
        ses = sessions.get(t.session_id)
        rows.append({
            "time": _fmt_dt(t.timestamp, tz), "plate": t.plate_number or "UNREAD", "vehicle_type": t.vehicle_type,
            "entry_time": _fmt_dt(ses.entry_time, tz) if ses else "", "duration": _fmt_dur(ses.duration_seconds) if ses else "",
            "camera": t.camera.name if t.camera else ("System" if t.source == "SYSTEM" else "Manual"), "match": t.status,
            "confidence": round(t.confidence * 100, 1),
        })
    durations = [sessions[t.session_id].duration_seconds for t in exits if t.session_id in sessions and sessions[t.session_id].duration_seconds is not None]
    status_counts = Counter(r["match"] for r in rows)
    return {
        "columns": [{"key": "time", "label": "Exit Time"}, {"key": "plate", "label": "Registration No."},
                    {"key": "vehicle_type", "label": "Vehicle Type"}, {"key": "entry_time", "label": "Entry Time"},
                    {"key": "duration", "label": "Duration"}, {"key": "camera", "label": "Camera"},
                    {"key": "match", "label": "Match Status"}, {"key": "confidence", "label": "Confidence %"}],
        "rows": rows,
        "summary": {"Total exits": sum(v for k, v in status_counts.items() if k in ExitStatus.COUNTED),
                    "Unmatched exits": status_counts.get(ExitStatus.UNMATCHED, 0),
                    "Average duration": _fmt_dur(sum(durations) / len(durations)) if durations else "-"},
        "chart": {"kind": "pie", "data": [{"name": k, "value": v} for k, v in status_counts.items()]},
    }


def _hour_buckets(items, tz, attr="timestamp"):
    c = Counter()
    for it in items:
        c[getattr(it, attr).astimezone(tz).hour] += 1
    return c


def _r_hourly(db, s, e, start, end, tz, sim):
    en = _hour_buckets(_entries(db, s, e, sim), tz)
    ex = _hour_buckets(_exits(db, s, e, sim), tz)
    rows = [{"hour": f"{h:02d}:00-{h:02d}:59", "entries": en[h], "exits": ex[h], "net": en[h] - ex[h], "total": en[h] + ex[h]} for h in range(24)]
    peak = max(rows, key=lambda r: r["total"])
    return {
        "columns": [{"key": "hour", "label": "Hour"}, {"key": "entries", "label": "Entries"}, {"key": "exits", "label": "Exits"},
                    {"key": "net", "label": "Net Change"}, {"key": "total", "label": "Total Movements"}],
        "rows": rows,
        "summary": {"Total entries": sum(en.values()), "Total exits": sum(ex.values()),
                    "Peak hour": peak["hour"] if peak["total"] else "-", "Peak movements": peak["total"]},
        "chart": {"kind": "bar", "x": "hour", "series": ["entries", "exits"]},
    }


def _daily_rows(db, s, e, start, end, tz, sim):
    en = defaultdict(list)
    for t in _entries(db, s, e, sim):
        en[t.timestamp.astimezone(tz).date()].append(t)
    ex = Counter(t.timestamp.astimezone(tz).date() for t in _exits(db, s, e, sim))
    durs = defaultdict(list)
    for ses in _durations(db, s, e, sim):
        if ses.duration_seconds is not None:
            durs[ses.exit_time.astimezone(tz).date()].append(ses.duration_seconds)
    rows = []
    d = start
    while d <= end:
        ents = en.get(d, [])
        types = Counter(t.vehicle_type for t in ents)
        rows.append({
            "date": d.isoformat(), "day": d.strftime("%a"), "entries": len(ents), "exits": ex.get(d, 0),
            "cars": types.get("CAR", 0), "two_wheelers": types.get("TWO_WHEELER", 0), "commercial": types.get("COMMERCIAL", 0),
            "unique_vehicles": len({t.plate_number for t in ents if t.plate_number}),
            "avg_duration": _fmt_dur(sum(durs[d]) / len(durs[d])) if durs.get(d) else "",
        })
        d += timedelta(days=1)
    cols = [{"key": "date", "label": "Date"}, {"key": "day", "label": "Day"}, {"key": "entries", "label": "Entries"},
            {"key": "exits", "label": "Exits"}, {"key": "cars", "label": "Cars"}, {"key": "two_wheelers", "label": "Two-Wheelers"},
            {"key": "commercial", "label": "Commercial"}, {"key": "unique_vehicles", "label": "Unique Vehicles"},
            {"key": "avg_duration", "label": "Avg Duration"}]
    total_en = sum(r["entries"] for r in rows)
    busiest = max(rows, key=lambda r: r["entries"]) if rows else None
    return {
        "columns": cols, "rows": rows,
        "summary": {"Total entries": total_en, "Total exits": sum(r["exits"] for r in rows),
                    "Daily average entries": round(total_en / max(1, len(rows)), 1),
                    "Busiest day": f"{busiest['date']} ({busiest['entries']})" if busiest and busiest["entries"] else "-"},
        "chart": {"kind": "bar", "x": "date", "series": ["entries", "exits"]},
    }


def _r_weekly(db, s, e, start, end, tz, sim):
    return _daily_rows(db, s, e, start, end, tz, sim)


def _r_monthly(db, s, e, start, end, tz, sim):
    rep = _daily_rows(db, s, e, start, end, tz, sim)
    rep["subtitle"] = start.strftime("%B %Y")
    rep["chart"] = {"kind": "line", "x": "date", "series": ["entries", "exits"]}
    return rep


def _r_category(db, s, e, start, end, tz, sim):
    en = Counter(t.vehicle_type for t in _entries(db, s, e, sim))
    cat = Counter(t.category for t in _entries(db, s, e, sim))
    ex = Counter(t.vehicle_type for t in _exits(db, s, e, sim))
    durs = defaultdict(list)
    for ses in _durations(db, s, e, sim):
        if ses.duration_seconds is not None:
            durs[ses.vehicle_type].append(ses.duration_seconds)
    rows = []
    for vt in ("CAR", "TWO_WHEELER", "COMMERCIAL"):
        rows.append({"vehicle_type": vt, "entries": en.get(vt, 0), "exits": ex.get(vt, 0),
                     "share": round(en.get(vt, 0) * 100 / max(1, sum(en.values())), 1),
                     "avg_duration": _fmt_dur(sum(durs[vt]) / len(durs[vt])) if durs.get(vt) else ""})
    return {
        "columns": [{"key": "vehicle_type", "label": "Vehicle Type"}, {"key": "entries", "label": "Entries"},
                    {"key": "exits", "label": "Exits"}, {"key": "share", "label": "Share of Entries %"},
                    {"key": "avg_duration", "label": "Avg Duration"}],
        "rows": rows,
        "summary": {"Total entries": sum(en.values()), **{f"{k} (parking category)": v for k, v in cat.items()}},
        "chart": {"kind": "pie", "data": [{"name": r["vehicle_type"], "value": r["entries"]} for r in rows]},
    }


def _r_camera(db, s, e, start, end, tz, sim):
    q = db.query(VehicleDetection).filter(VehicleDetection.detected_at >= s, VehicleDetection.detected_at < e)
    if not sim:
        q = q.filter(VehicleDetection.is_simulated.is_(False))
    stats = defaultdict(lambda: Counter())
    confs = defaultdict(list)
    for d in q.all():
        st = stats[d.camera_id]
        st["total"] += 1
        st[d.status] += 1
        if d.plate_number:
            confs[d.camera_id].append(d.plate_confidence)
    rows = []
    for cam in db.query(Camera).order_by(Camera.id).all():
        st = stats.get(cam.id, Counter())
        rows.append({
            "camera": cam.name, "code": cam.camera_code, "direction": cam.direction, "status": cam.status,
            "total": st["total"], "entries": st[DetectionStatus.ENTRY_CREATED], "exits": st[DetectionStatus.EXIT_RECORDED],
            "duplicates": st[DetectionStatus.DUPLICATE], "cooldown": st[DetectionStatus.COOLDOWN],
            "ocr_failed": st[DetectionStatus.FAILED_OCR],
            "avg_conf": round(sum(confs[cam.id]) * 100 / len(confs[cam.id]), 1) if confs.get(cam.id) else 0,
            "simulated": "Yes" if cam.is_simulated else "No",
        })
    return {
        "columns": [{"key": "camera", "label": "Camera"}, {"key": "code", "label": "ID"}, {"key": "direction", "label": "Direction"},
                    {"key": "status", "label": "Status"}, {"key": "total", "label": "Detections"}, {"key": "entries", "label": "Entries"},
                    {"key": "exits", "label": "Exits"}, {"key": "duplicates", "label": "Duplicates Blocked"},
                    {"key": "cooldown", "label": "Cooldown Ignored"}, {"key": "ocr_failed", "label": "OCR Failed"},
                    {"key": "avg_conf", "label": "Avg Confidence %"}, {"key": "simulated", "label": "Simulated"}],
        "rows": rows,
        "summary": {"Cameras": len(rows), "Total detections": sum(r["total"] for r in rows),
                    "Duplicates blocked": sum(r["duplicates"] + r["cooldown"] for r in rows)},
        "chart": {"kind": "bar", "x": "code", "series": ["entries", "exits", "duplicates"]},
    }


def _r_occupancy(db, s, e, start, end, tz, sim):
    snap = snapshot(db)
    rows = [{"category": c["label"], "capacity": c["total_capacity"], "occupied": c["occupied"], "available": c["available"],
             "occupancy_pct": c["occupancy_pct"], "threshold": c["alert_threshold_pct"], "state": c["alert_state"]}
            for c in snap["categories"]]
    rows.append({"category": "TOTAL", "capacity": snap["total_capacity"], "occupied": snap["occupied"], "available": snap["available"],
                 "occupancy_pct": snap["occupancy_pct"], "threshold": "", "state": ""})
    return {
        "subtitle": f"As of {datetime.now(tz):%d %b %Y %H:%M}",
        "columns": [{"key": "category", "label": "Category"}, {"key": "capacity", "label": "Capacity"},
                    {"key": "occupied", "label": "Occupied"}, {"key": "available", "label": "Available"},
                    {"key": "occupancy_pct", "label": "Occupancy %"}, {"key": "threshold", "label": "Alert Threshold %"},
                    {"key": "state", "label": "State"}],
        "rows": rows,
        "summary": {"Vehicles inside": snap["occupied"], "Available spaces": snap["available"], "Occupancy": f"{snap['occupancy_pct']}%"},
        "chart": {"kind": "bar", "x": "category", "series": ["occupied", "available"], "rows": rows[:-1]},
    }


def _r_peak_hours(db, s, e, start, end, tz, sim):
    days = max(1, (end - start).days + 1)
    en = _hour_buckets(_entries(db, s, e, sim), tz)
    ex = _hour_buckets(_exits(db, s, e, sim), tz)
    rows = [{"hour": f"{h:02d}:00", "avg_entries": round(en[h] / days, 2), "avg_exits": round(ex[h] / days, 2),
             "total": en[h] + ex[h]} for h in range(24)]
    ranked = sorted(rows, key=lambda r: r["total"], reverse=True)
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
    top = [r["hour"] for r in ranked[:3] if r["total"]]
    return {
        "columns": [{"key": "hour", "label": "Hour"}, {"key": "avg_entries", "label": "Avg Entries / Day"},
                    {"key": "avg_exits", "label": "Avg Exits / Day"}, {"key": "total", "label": "Total Movements"},
                    {"key": "rank", "label": "Rank"}],
        "rows": rows,
        "summary": {"Days analysed": days, "Top 3 peak hours": ", ".join(top) or "-",
                    "Peak entry hour": max(rows, key=lambda r: r["avg_entries"])["hour"] if any(en.values()) else "-",
                    "Peak exit hour": max(rows, key=lambda r: r["avg_exits"])["hour"] if any(ex.values()) else "-"},
        "chart": {"kind": "line", "x": "hour", "series": ["avg_entries", "avg_exits"]},
    }


def _r_accuracy(db, s, e, start, end, tz, sim):
    q = db.query(VehicleDetection).filter(
        VehicleDetection.detected_at >= s, VehicleDetection.detected_at < e,
        VehicleDetection.status != DetectionStatus.COOLDOWN,
    )
    if not sim:
        q = q.filter(VehicleDetection.is_simulated.is_(False))
    per = defaultdict(lambda: {"total": 0, "read": 0, "conf": [], "reviewed": 0, "corrected": 0, "pending": 0})
    for d in q.all():
        p = per[d.camera_id]
        p["total"] += 1
        if d.plate_number:
            p["read"] += 1
            p["conf"].append(d.plate_confidence)
        if d.reviewed_at:
            p["reviewed"] += 1
            if d.corrected_plate:
                p["corrected"] += 1
        if d.needs_review:
            p["pending"] += 1
    cams = {c.id: c for c in db.query(Camera).all()}
    rows = []
    for cid, p in per.items():
        cam = cams.get(cid)
        correct = p["read"] - p["corrected"]
        rows.append({
            "camera": cam.name if cam else "Manual", "total": p["total"], "read": p["read"],
            "read_rate": round(p["read"] * 100 / max(1, p["total"]), 1),
            "avg_conf": round(sum(p["conf"]) * 100 / len(p["conf"]), 1) if p["conf"] else 0,
            "reviewed": p["reviewed"], "corrected": p["corrected"], "pending": p["pending"],
            "accuracy": round(correct * 100 / max(1, p["total"]), 1),
        })
    tot = sum(r["total"] for r in rows)
    read = sum(r["read"] for r in rows)
    corr = sum(r["corrected"] for r in rows)
    return {
        "columns": [{"key": "camera", "label": "Camera"}, {"key": "total", "label": "Vehicle Passes"},
                    {"key": "read", "label": "Plates Read"}, {"key": "read_rate", "label": "Read Rate %"},
                    {"key": "avg_conf", "label": "Avg Confidence %"}, {"key": "reviewed", "label": "Reviewed"},
                    {"key": "corrected", "label": "Corrected"}, {"key": "pending", "label": "Pending Review"},
                    {"key": "accuracy", "label": "Est. Accuracy %"}],
        "rows": rows,
        "summary": {"Vehicle passes": tot, "Plate read rate": f"{round(read * 100 / max(1, tot), 1)}%",
                    "Estimated accuracy": f"{round((read - corr) * 100 / max(1, tot), 1)}%",
                    "Note": "Accuracy = plates read and not corrected by an operator / all passes"},
        "chart": {"kind": "bar", "x": "camera", "series": ["read_rate", "accuracy"]},
    }


# ---------------------------------------------------------------- exporters
def to_csv(rep: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([rep["title"]])
    w.writerow([rep["facility"], rep["subtitle"], f"Generated {rep['generated_at']}"])
    w.writerow([])
    w.writerow([c["label"] for c in rep["columns"]])
    for r in rep["rows"]:
        w.writerow([r.get(c["key"], "") for c in rep["columns"]])
    w.writerow([])
    for k, v in rep["summary"].items():
        w.writerow([k, v])
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx(rep: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    ws["A1"] = rep["title"]
    ws["A1"].font = Font(size=14, bold=True, color="0B2545")
    ws["A2"] = f"{rep['facility']}  |  {rep['subtitle']}  |  Generated {rep['generated_at']}"
    if rep.get("include_simulated"):
        ws["A3"] = "Includes simulated camera data"
        ws["A3"].font = Font(italic=True, color="C05621")
    header_row = 5
    fill = PatternFill("solid", fgColor="0B2545")
    for i, c in enumerate(rep["columns"], 1):
        cell = ws.cell(row=header_row, column=i, value=c["label"])
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(i)].width = max(12, len(c["label"]) + 4)
    for ri, r in enumerate(rep["rows"], header_row + 1):
        for ci, c in enumerate(rep["columns"], 1):
            ws.cell(row=ri, column=ci, value=r.get(c["key"], ""))
    last = header_row + len(rep["rows"])
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    sws = wb.create_sheet("Summary")
    for i, (k, v) in enumerate(rep["summary"].items(), 1):
        sws.cell(row=i, column=1, value=k).font = Font(bold=True)
        sws.cell(row=i, column=2, value=str(v))
    sws.column_dimensions["A"].width = 32
    sws.column_dimensions["B"].width = 40

    chart = rep.get("chart") or {}
    keys = [c["key"] for c in rep["columns"]]
    if chart.get("series") and chart.get("x") in keys and rep["rows"] and not chart.get("rows"):
        ch = LineChart() if chart["kind"] == "line" else BarChart()
        ch.title = rep["title"]
        ch.height, ch.width = 9, 22
        for sname in chart["series"]:
            if sname in keys:
                col = keys.index(sname) + 1
                ch.add_data(Reference(ws, min_col=col, min_row=header_row, max_row=last), titles_from_data=True)
        xcol = keys.index(chart["x"]) + 1
        ch.set_categories(Reference(ws, min_col=xcol, min_row=header_row + 1, max_row=last))
        ws.add_chart(ch, f"{get_column_letter(len(keys) + 2)}{header_row}")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(rep: dict) -> bytes:
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    page = landscape(A4) if len(rep["columns"]) > 6 else A4
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title=rep["title"])
    styles = getSampleStyleSheet()
    navy = colors.HexColor("#0B2545")
    story = [
        Paragraph(f"<font color='#0B2545'><b>{rep['title']}</b></font>", styles["Title"]),
        Paragraph(f"{rep['facility']} &nbsp;|&nbsp; {rep['subtitle']} &nbsp;|&nbsp; Generated {rep['generated_at']}", styles["Normal"]),
    ]
    if rep.get("include_simulated"):
        story.append(Paragraph("<font color='#C05621'><i>Includes simulated camera data</i></font>", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))
    summary = [[k, str(v)] for k, v in rep["summary"].items()]
    if summary:
        t = Table(summary, hAlign="LEFT")
        t.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story += [t, Spacer(1, 5 * mm)]

    chart = rep.get("chart") or {}
    rows_for_chart = chart.get("rows") or rep["rows"]
    if chart.get("series") and rows_for_chart and len(rows_for_chart) <= 40:
        series = [s for s in chart["series"] if all(isinstance(r.get(s, 0), (int, float)) for r in rows_for_chart)]
        if series:
            dwg = Drawing(page[0] - 30 * mm, 55 * mm)
            bc = VerticalBarChart()
            bc.x, bc.y, bc.height, bc.width = 30, 15, 45 * mm, page[0] - 50 * mm
            bc.data = [[float(r.get(s, 0) or 0) for r in rows_for_chart] for s in series]
            bc.categoryAxis.categoryNames = [str(r.get(chart["x"], ""))[:10] for r in rows_for_chart]
            bc.categoryAxis.labels.fontSize = 6
            bc.categoryAxis.labels.angle = 45 if len(rows_for_chart) > 12 else 0
            bc.categoryAxis.labels.dy = -6 if len(rows_for_chart) > 12 else 0
            bc.valueAxis.valueMin = 0
            palette = [colors.HexColor("#1D4ED8"), colors.HexColor("#F59E0B"), colors.HexColor("#DC2626")]
            for i in range(len(series)):
                bc.bars[i].fillColor = palette[i % 3]
            dwg.add(bc)
            story += [dwg, Paragraph(" / ".join(f"<font color='{['#1D4ED8', '#F59E0B', '#DC2626'][i % 3]}'>■</font> {s}" for i, s in enumerate(series)), styles["Normal"]), Spacer(1, 5 * mm)]

    data = [[c["label"] for c in rep["columns"]]] + [[str(r.get(c["key"], "")) for c in rep["columns"]] for r in rep["rows"]]
    if len(data) == 1:
        data.append(["No records"] + [""] * (len(rep["columns"]) - 1))
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF2F7")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()
