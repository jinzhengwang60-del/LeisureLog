"""Read-side grouping of a day's sessions into blocks a person would recognise."""

from collections import Counter
from dataclasses import asdict

SUMMED = (
    "recorded_seconds",
    "active_seconds",
    "afk_seconds",
    "unverified_seconds",
    "detected_afk_seconds",
    "retained_afk_seconds",
)


def _key(session):
    c = session.classification
    return (
        session.source,
        session.device,
        session.stream,
        session.app,
        c.category,
        c.content,
        session.context,
    )


def group_sessions(sessions, gap_seconds: float = 300) -> list[dict]:
    """Merge sessions with the same app, category and content when the gap since the
    previous one of that kind is at most ``gap_seconds``. Short switches to other apps
    in between stay separate and do not break the block. Times are summed, never
    taken from the block's span, so nothing is counted twice."""
    blocks, open_blocks = [], {}
    for session in sorted(sessions, key=lambda s: (s.start_time, s.id)):
        key = _key(session)
        block = open_blocks.get(key)
        if block and (session.start_time - block["end"]).total_seconds() <= gap_seconds:
            block["members"].append(session)
            block["end"] = max(block["end"], session.end_time)
        else:
            block = {"members": [session], "end": session.end_time}
            open_blocks[key] = block
            blocks.append(block)
    return [_describe(block["members"]) for block in blocks]


def _describe(members) -> dict:
    first = members[0]
    longest = max(members, key=lambda s: s.recorded_seconds)
    titles = Counter(s.title for s in members if s.title)
    return {
        "kind": "group",
        "id": f"group:{first.id}",
        "app": first.app,
        "title": titles.most_common(1)[0][0] if titles else longest.title,
        "url": longest.url,
        "start_time": first.start_time,
        "end_time": max(s.end_time for s in members),
        "classification": {
            **asdict(first.classification),
            "origin": "manual"
            if any(s.classification.origin == "manual" for s in members)
            else first.classification.origin,
        },
        "context": asdict(first.context) if first.context else None,
        **{name: sum(getattr(s, name) for s in members) for name in SUMMED},
        "session_count": len(members),
        "sessions": [
            asdict(s) for s in sorted(members, key=lambda s: (s.start_time, s.id), reverse=True)
        ],
    }
