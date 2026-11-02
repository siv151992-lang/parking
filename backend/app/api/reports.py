from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require
from ..services import reports
from ..services.audit import audit
from ..services.timeutil import local_today

router = APIRouter(prefix="/api/reports", tags=["Reports & Analytics"])

MIME = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@router.get("/types")
def report_types(_=Depends(require("reports.view"))):
    return [{"key": k, "title": v} for k, v in reports.REPORT_TYPES.items()]


def _build(db, rtype, start, end, include_simulated):
    today = local_today(db)
    if start is None:
        start = today - timedelta(days=6) if rtype in ("weekly", "peak_hours", "category", "camera", "accuracy") else today
    if end is None:
        end = start + timedelta(days=6) if rtype == "weekly" else (today if rtype in ("peak_hours", "category", "camera", "accuracy") else start)
    if end < start:
        raise HTTPException(400, "end date before start date")
    if (end - start).days > 366:
        raise HTTPException(400, "Maximum report range is 366 days")
    try:
        return reports.build_report(db, rtype, start, end, include_simulated)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{rtype}")
def get_report(rtype: str, start: date | None = None, end: date | None = None, include_simulated: bool = True,
               db: Session = Depends(get_db), _=Depends(require("reports.view"))):
    return _build(db, rtype, start, end, include_simulated)


@router.get("/{rtype}/export")
def export_report(rtype: str, request: Request, format: Literal["csv", "xlsx", "pdf"] = "xlsx", start: date | None = None,
                  end: date | None = None, include_simulated: bool = True, db: Session = Depends(get_db),
                  user=Depends(require("reports.view"))):
    rep = _build(db, rtype, start, end, include_simulated)
    content = {"csv": reports.to_csv, "xlsx": reports.to_xlsx, "pdf": reports.to_pdf}[format](rep)
    fname = f"{rtype}_{rep['period']['start']}_{rep['period']['end']}.{format}"
    audit(db, user, "EXPORT_REPORT", "report", rtype, {"format": format, **rep["period"]}, client_ip(request))
    db.commit()
    return Response(content, media_type=MIME[format], headers={"Content-Disposition": f'attachment; filename="{fname}"'})
