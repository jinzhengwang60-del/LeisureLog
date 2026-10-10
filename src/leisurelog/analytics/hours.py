"""Day x hour grid of activity for the statistics page (Beijing time)."""

from collections import defaultdict
from datetime import date, timedelta

from leisurelog.analytics.query import BEIJING, day_sessions

MAX_DAYS = 31


def hour_grid(repo, start: date, end: date) -> dict:
    """Counted seconds per category for each hour of each day in [start, end].

    A session's counted (active) time is spread over its clipped span in proportion
    to wall-clock time, because AFK deductions are not located inside a session.
    Ranges longer than MAX_DAYS keep the last MAX_DAYS days."""
    if end < start:
        raise ValueError("end must not be before start")
    truncated = (end - start).days + 1 > MAX_DAYS
    if truncated:
        start = end - timedelta(days=MAX_DAYS - 1)
    days = []
    current = start
    while current <= end:
        sessions, _, _ = day_sessions(repo, current)
        cells = [defaultdict(float) for _ in range(24)]
        for session in sessions:
            span = (session.end_time - session.start_time).total_seconds()
            if span <= 0 or session.active_seconds <= 0:
                continue
            rate = session.active_seconds / span
            moment = session.start_time.astimezone(BEIJING)
            finish = session.end_time.astimezone(BEIJING)
            while moment < finish:
                boundary = moment.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                piece = (min(boundary, finish) - moment).total_seconds()
                cells[moment.hour][session.classification.category] += piece * rate
                moment = boundary
        days.append(
            {
                "day": current.isoformat(),
                "hours": [
                    {
                        "active_seconds": round(sum(cell.values()), 3),
                        "top": max(cell, key=cell.get) if cell else None,
                        "categories": {k: round(v, 3) for k, v in cell.items() if v >= 0.5},
                    }
                    for cell in cells
                ],
            }
        )
        current += timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat(), "truncated": truncated,
            "days": days}
