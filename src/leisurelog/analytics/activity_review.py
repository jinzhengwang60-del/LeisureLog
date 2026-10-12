"""All-activity weekly review using calendar-day SQL facts and conservative purpose labels."""

from collections import defaultdict
from datetime import timedelta

from leisurelog.analytics.review import week_of


def _week(store, monday, today):
    facts = store.week_facts(monday, min(monday + timedelta(days=6), today))
    by_day, purposes = defaultdict(dict), defaultdict(float)
    for item in facts["days"]:
        by_day[item["day"]][item["purpose"]] = item["active_seconds"]
        purposes[item["purpose"]] += item["active_seconds"]
    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        values = by_day.get(day, {})
        days.append(
            {
                "day": day.isoformat(),
                "future": day > today,
                "purpose_seconds": values,
                "active_seconds": sum(values.values()),
            }
        )
    return {
        "days": days,
        "purposes": dict(purposes),
        "activities": facts["activities"],
        "projects": facts["projects"],
        "total": sum(purposes.values()),
    }


def activity_review(store, day, today):
    monday, _ = week_of(day)
    current = _week(store, monday, today)
    previous = _week(store, monday - timedelta(days=7), today)

    def identity(item):
        return tuple(item[key] for key in ("app", "category", "content", "purpose", "project_id"))

    seen = {identity(item) for item in previous["activities"] if item["active_seconds"] >= 60}
    ranked = sorted(current["activities"], key=lambda item: (-item["active_seconds"], item["app"]))
    return {
        "activity_seconds": current["total"],
        "previous_activity_seconds": previous["total"],
        "all_days": current["days"],
        "purpose_seconds": current["purposes"],
        "previous_purpose_seconds": previous["purposes"],
        "purpose_unknown_seconds": current["purposes"].get("unknown", 0),
        "all_top_activities": [
            {**item, "new": identity(item) not in seen}
            for item in ranked
            if item["active_seconds"] >= 60
        ][:8],
        "all_activity_count": sum(item["active_seconds"] > 0 for item in ranked),
        "project_count": sum(
            item["project_id"] is not None and item["active_seconds"] > 0
            for item in current["projects"]
        ),
        "project_seconds": current["projects"],
        "project_options": store.projects(),
    }
