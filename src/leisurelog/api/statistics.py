import csv
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from leisurelog.analytics.hours import hour_grid
from leisurelog.analytics.range import statistics
from leisurelog.api.routes import Service
from leisurelog.api.schemas import PurposeFilter

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
    purpose: PurposeFilter = "",
    project_id: str = Query(default="", max_length=100),
):
    try:
        return statistics(svc.repo, start, end, granularity, purpose, project_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/statistics/hours")
def read_hour_grid(
    svc: Service,
    start: date = Query(le=date(9998, 12, 31)),
    end: date = Query(le=date(9998, 12, 31)),
    purpose: PurposeFilter = "",
    project_id: str = Query(default="", max_length=100),
):
    try:
        return hour_grid(svc.repo, start, end, purpose, project_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/statistics/export")
def export_statistics(
    svc: Service,
    start: date = Query(le=date(9998, 12, 31)),
    end: date = Query(le=date(9998, 12, 31)),
    granularity: Literal["auto", "day", "month"] = "auto",
    purpose: PurposeFilter = "",
    project_id: str = Query(default="", max_length=100),
):
    try:
        data = statistics(svc.repo, start, end, granularity, purpose, project_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "日期",
            "有匹配记录",
            "计入秒数",
            "原始秒数",
            "已扣除离开秒数",
            "状态待确认秒数",
            "检测到离开秒数",
            "策略保留离开秒数",
        ]
    )
    for row in data["trend"]:
        writer.writerow(
            [
                row["period"],
                "是" if row["has_records"] else "否",
                *[
                    round(row[key], 3)
                    for key in (
                        "active_seconds",
                        "recorded_seconds",
                        "afk_seconds",
                        "unverified_seconds",
                        "detected_afk_seconds",
                        "retained_afk_seconds",
                    )
                ],
            ]
        )
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="leisurelog-{start}-{end}.csv"'},
    )
