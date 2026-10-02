from collections import defaultdict

from leisurelog.domain.models import Session


def summarize(sessions: list[Session]) -> dict:
    categories = defaultdict(float)
    active = defaultdict(float)
    for session in sessions:
        categories[session.classification.category] += session.recorded_seconds
        active[session.classification.category] += session.active_seconds
    return {
        "session_count": len(sessions),
        "recorded_seconds_by_category": dict(categories),
        "active_seconds_by_category": dict(active),
        "afk_seconds": sum(s.afk_seconds for s in sessions),
        "detected_afk_seconds": sum(s.detected_afk_seconds for s in sessions),
        "retained_afk_seconds": sum(s.retained_afk_seconds for s in sessions),
        "unverified_seconds": sum(s.unverified_seconds for s in sessions),
        "scope": (
            "configured timing policy applied; detected AFK preserved; no cross-stream dedup"
        ),
    }
