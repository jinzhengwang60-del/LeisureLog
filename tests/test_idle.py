from datetime import datetime, timedelta, timezone

import pytest

from leisurelog.domain.idle import apply_idle
from leisurelog.domain.models import ActivityEvent, IdleEvent
from leisurelog.domain.sessionization import merge_sessions

START = datetime(2026, 9, 29, 23, 59, 30, tzinfo=timezone.utc)


def at(seconds):
    return START + timedelta(seconds=seconds)


def away(start, end, status="afk", device="pc", source="aw"):
    return IdleEvent(
        str(start) + str(end) + status, source, "idle", device, at(start), at(end), status
    )


def calculate(intervals, statuses):
    events = [
        ActivityEvent(str(i), "aw", "window", "pc", at(a), at(b), "game")
        for i, (a, b) in enumerate(intervals)
    ]
    sessions = merge_sessions(events, 60)
    apply_idle(sessions, events, statuses)
    return sessions


@pytest.mark.parametrize(
    "idle,expected",
    [
        ([away(0, 100, "not-afk")], (100, 0, 100, 0)),
        ([away(0, 100)], (100, 100, 0, 0)),
        ([away(20, 40), away(30, 60)], (100, 40, 60, 60)),
        ([away(-20, 20), away(80, 120)], (100, 40, 60, 60)),
        ([], (100, 0, 100, 100)),
        ([away(0, 100, device="other")], (100, 0, 100, 100)),
        ([away(0, 100, source="other")], (100, 0, 100, 100)),
        ([away(0, 100, device="unknown")], (100, 0, 100, 100)),
        ([away(0, 100, "not-afk"), away(20, 40)], (100, 20, 80, 0)),
        ([away(100, 120), away(-20, 0)], (100, 0, 100, 100)),
    ],
)
def test_afk_intervals(idle, expected):
    session = calculate([(0, 100)], idle)[0]
    assert (
        session.recorded_seconds,
        session.afk_seconds,
        session.active_seconds,
        session.unverified_seconds,
    ) == expected


def test_union_excludes_bridge_gaps_and_duplicate_events():
    session = calculate([(0, 40), (20, 50), (70, 100)], [away(0, 100, "not-afk"), away(40, 80)])[0]
    assert session.recorded_seconds == 80
    assert session.afk_seconds == 20
    assert session.active_seconds == 60
    assert session.unverified_seconds == 0
    assert len(session.event_ids) == 3
