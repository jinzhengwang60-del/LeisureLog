"""Half-open interval arithmetic; AFK wins if source statuses conflict."""

from collections import defaultdict

from leisurelog.domain.models import ActivityEvent, IdleEvent, Session
from leisurelog.domain.timing import protected_intervals


def union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def seconds(intervals):
    return sum((end - start).total_seconds() for start, end in intervals)


def intersection(left, right):
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        start, end = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if start < end:
            result.append((start, end))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return result


def apply_idle(sessions: list[Session], events: list[ActivityEvent], idle: list[IdleEvent]):
    by_id = {event.id: event for event in events}
    statuses = defaultdict(list)
    for event in idle:
        # Missing device identity is not evidence that two records belong to the same PC.
        if event.device != "unknown":
            statuses[(event.source, event.device)].append(event)
    coverage = {}
    for key, values in statuses.items():
        coverage[key] = (
            union((e.start_time, e.end_time) for e in values if e.status == "afk"),
            union((e.start_time, e.end_time) for e in values),
        )
    for session in sessions:
        recorded = union((by_id[key].start_time, by_id[key].end_time) for key in session.event_ids)
        away, known = coverage.get((session.source, session.device), ([], []))
        session.recorded_seconds = seconds(recorded)
        protected = union(protected_intervals([by_id[key] for key in session.event_ids]))
        session.detected_afk_seconds = seconds(intersection(recorded, away))
        session.retained_afk_seconds = seconds(
            intersection(intersection(recorded, away), protected)
        )
        session.afk_seconds = max(0, session.detected_afk_seconds - session.retained_afk_seconds)
        session.active_seconds = max(0, session.recorded_seconds - session.afk_seconds)
        session.unverified_seconds = max(
            0,
            session.recorded_seconds - seconds(intersection(recorded, known)),
        )
