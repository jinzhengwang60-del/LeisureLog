from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from leisurelog.analytics.hours import hour_grid
from leisurelog.analytics.range import statistics
from leisurelog.api.routes import Service

router = APIRouter()


@router.get("/statistics", include_in_schema=False)
def page():
    return FileResponse(Path(__file__).parent / "static/statistics.html")


@router.get("/api/statistics")
def read_statistics(
    svc: Service,
    start: date = Query(le=date(9998, 12, 31)),
    end: date = Query(le=date(9998, 12, 31)),
    granularity: Literal["auto", "day", "month"] = "auto",
):
    try:
        return statistics(svc.repo, start, end, granularity)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/statistics/hours")
def read_hour_grid(
    svc: Service,
    start: date = Query(le=date(9998, 12, 31)),
    end: date = Query(le=date(9998, 12, 31)),
):
    try:
        return hour_grid(svc.repo, start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
