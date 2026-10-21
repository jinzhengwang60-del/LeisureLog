from contextlib import contextmanager
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text

from leisurelog import DATABASE_REVISION, __version__
from leisurelog.adapters.activitywatch import SourceUnavailable
from leisurelog.api.schemas import (
    BatchOverrideRequest,
    EventSelection,
    OverrideRequest,
    SyncRequest,
    TimingRequest,
)
from leisurelog.domain.models import Classification
from leisurelog.repositories.sqlite import SQLiteRepository
from leisurelog.services.processing import ProcessingService

router = APIRouter()


def processing_service(request: Request, write):
    state = request.app.state
    with state.sessions() as db:
        # Serialize writers across processes before reading derived state.
        if write:
            db.execute(text("BEGIN IMMEDIATE"))
        else:
            # Keep linked events, sessions and idle states in one consistent read snapshot.
            db.execute(text("BEGIN"))
        with_context = ProcessingService(
            SQLiteRepository(db),
            state.pipeline,
            state.settings.session_gap_seconds,
        )
        try:
            yield with_context
            db.commit()
        except Exception:
            db.rollback()
            raise


def service(request: Request):
    yield from processing_service(request, request.method != "GET")


def read_service(request: Request):
    yield from processing_service(request, False)


# Commit/rollback before sending a response so an immediately following read sees
# the saved state, and a failed commit cannot be reported as a successful save.
Service = Annotated[ProcessingService, Depends(service, scope="function")]
ReadService = Annotated[ProcessingService, Depends(read_service, scope="function")]
Limit = Annotated[int, Query(ge=1, le=1000)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/health")
def health(request: Request):
    with request.app.state.sessions() as db:
        try:
            revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        except Exception as exc:
            raise HTTPException(503, "Database is not migrated; run alembic upgrade head") from exc
    if revision != DATABASE_REVISION:
        raise HTTPException(503, "Unexpected database revision")
    return {"status": "ok", "database_revision": revision, "version": __version__}


@router.get("/api/sync/status")
def sync_status(request: Request):
    return request.app.state.scheduler.snapshot()


@router.post("/api/sync/activitywatch")
def sync(body: SyncRequest, request: Request):
    try:
        # Network requests must finish before acquiring the SQLite writer lock.
        records = request.app.state.source.fetch(body.start, body.end, body.buckets)
    except SourceUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    with contextmanager(processing_service)(request, True) as svc:
        return svc.ingest(records)


@router.get("/api/events")
def events(svc: Service, limit: Limit = 100, offset: Offset = 0):
    return [asdict(e) for e in svc.repo.resolved_events(offset=offset, limit=limit)]


@router.get("/api/sessions")
def sessions(svc: Service, limit: Limit = 100, offset: Offset = 0):
    return [asdict(s) for s in svc.repo.sessions(offset=offset, limit=limit)]


@router.post("/api/reprocess")
def reprocess(svc: Service):
    return svc.rebuild()


@router.put("/api/events/overrides")
def override_batch(body: BatchOverrideRequest, svc: Service):
    try:
        return svc.override_many(
            body.event_ids,
            Classification(
                category=body.category,
                content=body.content,
                tags=tuple(body.tags),
                origin="manual",
            ),
            body.remember_scope,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Selected events not found; refresh the list") from exc


@router.delete("/api/events/overrides")
def remove_override_batch(body: EventSelection, svc: Service):
    try:
        return svc.override_many(body.event_ids, None)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Selected events not found; refresh the list") from exc


@router.put("/api/events/{event_id}/override")
def override(event_id: str, body: OverrideRequest, svc: Service):
    try:
        return svc.override(
            event_id,
            Classification(
                category=body.category,
                content=body.content,
                tags=tuple(body.tags),
                origin="manual",
            ),
        )
    except KeyError as exc:
        raise HTTPException(404, "Event not found") from exc


@router.delete("/api/events/{event_id}/override")
def remove_override(event_id: str, svc: Service):
    try:
        return svc.override(event_id, None)
    except KeyError as exc:
        raise HTTPException(404, "Event not found") from exc


@router.get("/api/stats/summary")
def summary(svc: Service):
    return svc.repo.summary_totals()


@router.get("/api/idle-events")
def idle_events(svc: Service, limit: Limit = 100, offset: Offset = 0):
    return [asdict(e) for e in svc.repo.idle_events(offset=offset, limit=limit)]


@router.get("/api/classification/rules")
def learned_rules(svc: Service):
    return [asdict(rule) for rule in svc.repo.learned_rules()]


@router.delete("/api/classification/rules/{rule_id}")
def delete_learned_rule(rule_id: str, svc: Service):
    try:
        svc.repo.delete_rule(rule_id)
        return svc.rebuild()
    except KeyError as exc:
        raise HTTPException(404, "Rule not found") from exc


@router.get("/api/browser/status")
def browser_status(request: Request, svc: Service):
    try:
        available = request.app.state.source._get("/api/0/buckets/")
        if not isinstance(available, dict):
            raise ValueError("Invalid buckets")
    except Exception as exc:
        raise HTTPException(502, "ActivityWatch browser status unavailable") from exc
    facts = svc.repo.browser_facts()
    buckets = []
    for key, metadata in available.items():
        if metadata.get("type") != "web.tab.current":
            continue
        records = facts["streams"].get(key, {"devices": [], "records": 0, "last_record_at": None})
        buckets.append(
            {
                "id": key,
                "hostname": metadata.get("hostname"),
                "devices": sorted(records["devices"]),
                "records": records["records"],
                "last_record_at": records["last_record_at"],
            }
        )
    return {
        "buckets": buckets,
        "browser_records": facts["browser_records"],
        "matched_segments": facts["matched_segments"],
        "supported_browsers": ["Edge", "Chrome"],
    }


@router.put("/api/events/timing")
def timing_override(body: TimingRequest, svc: Service):
    try:
        return svc.timing_many(body.event_ids, body.policy)
    except KeyError as exc:
        raise HTTPException(404, "Selected activity changed; refresh the list") from exc
