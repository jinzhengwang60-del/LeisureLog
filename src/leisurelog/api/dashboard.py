from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from leisurelog.analytics.query import BEIJING, dashboard, day_sessions, ribbon
from leisurelog.api.routes import Limit, Offset, Service
from leisurelog.api.schemas import PurposeFilter

router = APIRouter()


@router.get("/", include_in_schema=False)
def home():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@router.get("/api/dashboard")
def read_dashboard(
    svc: Service,
    day: date | None = None,
    app: str = Query(default="", max_length=300),
    category: str = Query(default="", max_length=100),
    query: str = Query(default="", max_length=300),
    limit: Limit = 50,
    offset: Offset = 0,
    view: Literal["sessions", "grouped"] = "sessions",
    min_seconds: float = Query(default=0, ge=0, le=3600),
    purpose: PurposeFilter = "",
    project_id: str = Query(default="", max_length=100),
):
    return dashboard(
        svc.repo,
        day or datetime.now(BEIJING).date(),
        app,
        category,
        query,
        limit,
        offset,
        view,
        min_seconds,
        purpose,
        project_id,
    )


@router.get("/api/dashboard/ribbon")
def read_ribbon(
    svc: Service,
    day: date | None = None,
    app: str = Query(default="", max_length=300),
    category: str = Query(default="", max_length=100),
    query: str = Query(default="", max_length=300),
    purpose: PurposeFilter = "",
    project_id: str = Query(default="", max_length=100),
):
    return ribbon(
        svc.repo, day or datetime.now(BEIJING).date(), app, category, query, purpose, project_id
    )


@router.get("/api/sessions/{session_id}/details")
def details(session_id: str, svc: Service, day: date):
    sessions, events, idle = day_sessions(svc.repo, day)
    session = next((s for s in sessions if s.id == session_id), None)
    if session is None:
        raise HTTPException(404, "Session changed or not found for this day; refresh the list")
    related = [e for e in events if e.id in session.event_ids]
    related.sort(key=lambda e: (e.start_time, e.id))
    states = [
        e
        for e in idle
        if e.device == session.device
        and e.source == session.source
        and e.start_time < session.end_time
        and e.end_time > session.start_time
    ]
    return {
        "session": asdict(session),
        "events": [asdict(e) for e in related],
        "idle_events": [asdict(e) for e in states],
        "window_events": [
            asdict(e) for e in svc.repo.events(ids={r.window_event_id for r in related})
        ],
        "browser_events": [
            asdict(e)
            for e in svc.repo.browser_events(
                ids={r.browser_event_id for r in related if r.browser_event_id is not None}
            )
        ],
    }
