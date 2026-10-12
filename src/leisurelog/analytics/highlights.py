"""What the day's leisure looked like: total, the split by kind of activity, and the top items.
Always computed from the whole day so list filters do not change the headline."""

from collections import defaultdict

from leisurelog.analytics.range import LEISURE_CATEGORIES
from leisurelog.domain.activity_context import PURPOSES

GROUPS = ("leisure", "work", "other", "unknown")


def group_of(category: str) -> str:
    if category in LEISURE_CATEGORIES:
        return "leisure"
    return category if category in ("work", "unknown") else "other"


def highlights(sessions, top: int = 5) -> dict:
    groups = dict.fromkeys(GROUPS, 0.0)
    activities: dict[tuple[str, str], dict] = {}
    by_category = defaultdict(float)
    purposes = dict.fromkeys(PURPOSES, 0.0)
    projects = defaultdict(float)
    all_activities = {}
    for session in sessions:
        category = session.classification.category
        purpose = session.context.purpose
        project_id = session.context.project_id
        purposes[purpose] = purposes.get(purpose, 0) + session.active_seconds
        projects[project_id] += session.active_seconds
        content = session.classification.content
        entry = all_activities.setdefault(
            (session.app, category, content, purpose, project_id),
            {
                "app": session.app,
                "category": category,
                "content": content,
                "purpose": purpose,
                "project_id": project_id,
                "active_seconds": 0.0,
            },
        )
        entry["active_seconds"] += session.active_seconds
        group = group_of(category)
        groups[group] += session.active_seconds
        if group != "leisure":
            continue
        by_category[category] += session.active_seconds
        content = session.classification.content
        key = (category, content or session.app)
        entry = activities.setdefault(
            key,
            {"category": category, "content": content, "app": session.app, "active_seconds": 0.0},
        )
        entry["active_seconds"] += session.active_seconds
    ranked = sorted(activities.values(), key=lambda a: (-a["active_seconds"], a["app"]))
    return {
        "activity_seconds": sum(s.active_seconds for s in sessions),
        "recorded_seconds": sum(s.recorded_seconds for s in sessions),
        "unverified_seconds": sum(s.unverified_seconds for s in sessions),
        "purpose_seconds": purposes,
        "project_seconds": [
            {"project_id": key, "active_seconds": value} for key, value in projects.items()
        ],
        "top_all_activities": sorted(
            (a for a in all_activities.values() if a["active_seconds"] >= 1),
            key=lambda a: (-a["active_seconds"], a["app"]),
        )[:top],
        "leisure_seconds": groups["leisure"],
        "groups": groups,
        "leisure_by_category": dict(by_category),
        "top_activities": [a for a in ranked if a["active_seconds"] >= 1][:top],
    }
