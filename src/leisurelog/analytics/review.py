"""A week in review, Monday to Sunday (Beijing): how much leisure, on what, on which days,
compared with the week before. Read-only and built from the same day views as the home page."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from leisurelog.analytics.highlights import group_of, highlights
from leisurelog.analytics.query import BEIJING, day_sessions

LATE_START, LATE_END = time(0), time(5)


def week_of(day: date) -> tuple[date, date]:
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def _late_seconds(session, day: date) -> float:
    """Leisure between midnight and 5 a.m., scaled by the share of the session that counted."""
    start = datetime.combine(day, LATE_START, BEIJING)
    end = datetime.combine(day, LATE_END, BEIJING)
    overlap = (min(session.end_time, end) - max(session.start_time, start)).total_seconds()
    if overlap <= 0 or session.recorded_seconds <= 0:
        return 0.0
    return overlap * session.active_seconds / session.recorded_seconds


def _week(repo, monday: date, today: date) -> dict:
    days, activities = [], {}
    by_category = defaultdict(float)
    longest, late = None, 0.0
    for offset in range(7):
        day = monday + timedelta(days=offset)
        if day > today:
            days.append({"day": day.isoformat(), "future": True, "groups": None,
                         "leisure_by_category": {}})
            continue
        sessions, _, _ = day_sessions(repo, day)
        summary = highlights(sessions, top=0)
        days.append({"day": day.isoformat(), "future": False, "groups": summary["groups"],
                     "leisure_by_category": summary["leisure_by_category"]})
        for category, seconds in summary["leisure_by_category"].items():
            by_category[category] += seconds
        for session in sessions:
            category = session.classification.category
            if group_of(category) != "leisure" or session.active_seconds <= 0:
                continue
            late += _late_seconds(session, day)
            name = session.classification.content or session.app
            entry = activities.setdefault(
                (category, name),
                {"category": category, "content": session.classification.content,
                 "app": session.app, "active_seconds": 0.0, "days": set()},
            )
            entry["active_seconds"] += session.active_seconds
            entry["days"].add(day.isoformat())
            if longest is None or session.active_seconds > longest["active_seconds"]:
                longest = {"category": category, "content": session.classification.content,
                           "app": session.app, "active_seconds": session.active_seconds,
                           "start_time": session.start_time.isoformat()}
    totals = defaultdict(float)
    for entry in days:
        for group, seconds in (entry["groups"] or {}).items():
            totals[group] += seconds
    return {
        "days": days,
        "totals": dict(totals),
        "leisure_by_category": dict(by_category),
        "activities": activities,
        "longest": longest,
        "late_night_seconds": late,
        "days_with_records": sum(1 for d in days if d["groups"] and sum(d["groups"].values()) > 0),
    }


def review(repo, day: date, today: date, top: int = 8) -> dict:
    monday, sunday = week_of(day)
    current = _week(repo, monday, today)
    previous = _week(repo, monday - timedelta(days=7), today)
    seen_before = set(previous["activities"])
    ranked = sorted(current["activities"].items(), key=lambda kv: -kv[1]["active_seconds"])
    top_activities = [
        {**{k: v for k, v in entry.items() if k != "days"},
         "days": len(entry["days"]), "new": key not in seen_before}
        for key, entry in ranked[:top] if entry["active_seconds"] >= 60
    ]
    leisure = current["totals"].get("leisure", 0.0)
    busiest = max(
        (d for d in current["days"] if d["groups"]),
        key=lambda d: d["groups"]["leisure"],
        default=None,
    )
    return {
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        "is_current": monday <= today <= sunday,
        "has_next": sunday < today,
        "timezone": "Asia/Shanghai",
        "leisure_seconds": leisure,
        "previous_leisure_seconds": previous["totals"].get("leisure", 0.0),
        "totals": current["totals"],
        "days": current["days"],
        "days_with_records": current["days_with_records"],
        "leisure_by_category": current["leisure_by_category"],
        "previous_leisure_by_category": previous["leisure_by_category"],
        "top_activities": top_activities,
        "activity_count": len(current["activities"]),
        "longest_session": current["longest"],
        "late_night_seconds": current["late_night_seconds"],
        "busiest_day": (
            {"day": busiest["day"], "leisure_seconds": busiest["groups"]["leisure"]}
            if busiest and busiest["groups"]["leisure"] > 0 else None
        ),
    }
