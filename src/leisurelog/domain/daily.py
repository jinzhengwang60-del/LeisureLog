"""Exact calendar-day attribution from unioned activity intervals, never prorated spans."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from leisurelog.domain.idle import intersection, seconds, union
from leisurelog.domain.models import ActivityEvent, IdleEvent, Session
from leisurelog.domain.timing import protected_intervals

BEIJING = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class DailyActivity:
    session_id: str
    day: date
    app: str
    category: str
    content: str | None
    recorded_seconds: float
    active_seconds: float
    afk_seconds: float
    detected_afk_seconds: float
    retained_afk_seconds: float
    unverified_seconds: float


def daily_activity(sessions: list[Session], events: list[ActivityEvent], idle: list[IdleEvent]):
    by_id = {e.id: e for e in events}
    statuses = defaultdict(list)
    for event in idle:
        if event.device != "unknown":
            statuses[event.source, event.device].append(event)
    coverage = {
        key: (
            union((e.start_time, e.end_time) for e in values if e.status == "afk"),
            union((e.start_time, e.end_time) for e in values),
        )
        for key, values in statuses.items()
    }
    result = []
    for session in sessions:
        recorded = union((by_id[key].start_time, by_id[key].end_time) for key in session.event_ids)
        days = defaultdict(list)
        for start, end in recorded:
            while start < end:
                day = start.astimezone(BEIJING).date()
                midnight = datetime.combine(day + timedelta(days=1), time.min, BEIJING)
                segment_end = min(end, midnight)
                days[day].append((start, segment_end))
                start = segment_end
        away, known = coverage.get((session.source, session.device), ([], []))
        protected = union(protected_intervals([by_id[key] for key in session.event_ids]))
        for day, intervals in days.items():
            total = seconds(intervals)
            detected = seconds(intersection(intervals, away))
            retained = seconds(intersection(intersection(intervals, away), protected))
            afk = max(0, detected - retained)
            unverified = max(0, total - seconds(intersection(intervals, known)))
            result.append(
                DailyActivity(
                    session.id,
                    day,
                    session.app,
                    session.classification.category,
                    session.classification.content,
                    total,
                    max(0, total - afk),
                    afk,
                    detected,
                    retained,
                    unverified,
                )
            )
    return result
