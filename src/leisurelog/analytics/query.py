"""Read-side day analysis with timing recalculated at calendar boundaries."""

from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta, timezone

from leisurelog.analytics.grouping import group_sessions
from leisurelog.analytics.highlights import highlights
from leisurelog.analytics.summary import summarize
from leisurelog.domain.idle import apply_idle

BEIJING = timezone(timedelta(hours=8))


def clip_sessions(sessions, events, idle, start: datetime, end: datetime):
    """Recalculate a half-open range from evidence, preserving manual timing policies."""
    events = [
        replace(e, start_time=max(e.start_time, start), end_time=min(e.end_time, end))
        for e in events
        if e.start_time < end and e.end_time > start
    ]
    ids = {e.id for e in events}
    sessions = [
        replace(
            s,
            start_time=max(s.start_time, start),
            end_time=min(s.end_time, end),
            event_ids=[key for key in s.event_ids if key in ids],
        )
        for s in sessions
        if s.start_time < end and s.end_time > start
    ]
    sessions = [s for s in sessions if s.event_ids]
    apply_idle(sessions, events, idle)
    return sessions, events, idle


def day_sessions(repo, day: date):
    start = datetime.combine(day, time.min, BEIJING)
    end = start + timedelta(days=1)
    return clip_sessions(
        repo.sessions(start=start, end=end),
        repo.resolved_events(start=start, end=end),
        repo.idle_events(start=start, end=end),
        start,
        end,
    )


def _matches(s, app: str, category: str, query: str, purpose="", project_id="") -> bool:
    return (
        (not app or s.app == app)
        and (not purpose or s.context.purpose == purpose)
        and (
            not project_id
            or (
                s.context.project_id is None
                if project_id == "none"
                else s.context.project_id == project_id
            )
        )
        and (not category or s.classification.category == category)
        and (
            not query
            or query.casefold()
            in (s.app + " " + s.title + " " + (s.classification.content or "")).casefold()
        )
    )


def ribbon(repo, day: date, app: str, category: str, query: str, purpose="", project_id=""):
    """Compact day timeline: only what the 24h strip draws, clipped to the Beijing day."""
    sessions, _, _ = day_sessions(repo, day)
    filtered = sorted(
        (s for s in sessions if _matches(s, app, category, query, purpose, project_id)),
        key=lambda s: (s.start_time, s.id),
    )
    return {
        "day": day.isoformat(),
        "items": [
            {
                "id": s.id,
                "start": round(s.start_time.timestamp() * 1000),
                "end": round(s.end_time.timestamp() * 1000),
                "app": s.app,
                "category": s.classification.category,
                "content": s.classification.content,
                "active_seconds": s.active_seconds,
                "purpose": s.context.purpose,
                "project_id": s.context.project_id,
            }
            for s in filtered
        ],
    }


def dashboard(
    repo,
    day: date,
    app: str,
    category: str,
    query: str,
    limit: int,
    offset: int,
    view: str = "sessions",
    min_seconds: float = 0,
    purpose: str = "",
    project_id: str = "",
):
    """Day list. ``view="grouped"`` merges nearby sessions of the same activity;
    ``min_seconds`` hides list entries shorter than that (the summary still counts them)."""
    sessions, _, _ = day_sessions(repo, day)
    options = {
        "apps": sorted({s.app for s in sessions}),
        "categories": sorted({s.classification.category for s in sessions}),
        "projects": repo.projects(),
    }
    filtered = [s for s in sessions if _matches(s, app, category, query, purpose, project_id)]
    if view == "grouped":
        entries = group_sessions(filtered)
    else:
        entries = [asdict(s) for s in filtered]
    shown = [e for e in entries if e["recorded_seconds"] >= min_seconds]
    shown.sort(key=lambda e: (e["start_time"], e["id"]), reverse=True)
    return {
        "day": day.isoformat(),
        "timezone": "Asia/Shanghai",
        "view": view,
        "total": len(shown),
        "hidden_short": len(entries) - len(shown),
        "options": options,
        "summary": summarize(filtered),
        "highlights": highlights(sessions),
        "items": shown[offset : offset + limit],
    }
