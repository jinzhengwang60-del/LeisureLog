"""Exact weekly timing regressions, collected by the normal test suite."""

from datetime import datetime, timedelta, timezone

import pytest

from leisurelog.domain.games import Game
from leisurelog_plugins.playnite import CoverIndex

pytest_plugins = ["tests.test_pipeline"]
BEIJING = timezone(timedelta(hours=8))


def ingest_window(client, payloads, app, start, end, idle):
    payloads[:] = [{
        "id": 100,
        "timestamp": start.isoformat(),
        "duration": (end - start).total_seconds(),
        "data": {"app": "GenshinImpact.exe", "title": "原神"},
    }]
    app.state.test_idle_payloads[:] = [{
        "id": i + 100,
        "timestamp": begin.isoformat(),
        "duration": (finish - begin).total_seconds(),
        "data": {"status": status},
    } for i, (begin, finish, status) in enumerate(idle)]
    client.post("/api/sync/activitywatch", json={
        "start": (start - timedelta(hours=1)).isoformat(),
        "end": (end + timedelta(hours=1)).isoformat(),
    }).raise_for_status()


def test_continuous_four_hours_across_midnight_is_the_longest_session(app_context):
    client, app, payloads, _, _ = app_context
    start = datetime(2026, 9, 28, 23, tzinfo=BEIJING)
    end = start + timedelta(hours=4)
    ingest_window(client, payloads, app, start, end, [(start, end, "not-afk")])
    sessions = client.get("/api/sessions").json()
    assert len(sessions) == 1 and sessions[0]["active_seconds"] == 14400
    data = client.get("/api/review", params={"day": "2026-09-29"}).json()
    assert data["leisure_seconds"] == 14400
    assert data["longest_session"]["active_seconds"] == 14400


def test_afk_before_five_is_not_late_night_leisure(app_context):
    client, app, payloads, _, _ = app_context
    start = datetime(2026, 9, 29, 4, tzinfo=BEIJING)
    five = start + timedelta(hours=1)
    end = start + timedelta(hours=2)
    ingest_window(client, payloads, app, start, end,
                  [(start, five, "afk"), (five, end, "not-afk")])
    data = client.get("/api/review", params={"day": "2026-09-29"}).json()
    assert data["leisure_seconds"] == 3600
    assert data["late_night_seconds"] == 0


def test_title_scoped_shared_process_does_not_assign_an_unrelated_cover():
    game = Game("minecraft", "Minecraft（PCL）", True, "", (),
                (("javaw.exe", "Minecraft"),))
    index = CoverIndex((game,), {})
    assert index.game_for("Another Java Game", ["javaw.exe"]) is None


@pytest.mark.parametrize("first_status,expected", [("afk", 0), ("not-afk", 3600)])
def test_late_night_counts_exact_afk_intersections(app_context, first_status, expected):
    client, app, payloads, _, _ = app_context
    start = datetime(2026, 9, 29, 4, tzinfo=BEIJING)
    five, end = start + timedelta(hours=1), start + timedelta(hours=2)
    other_status = "afk" if first_status == "not-afk" else "not-afk"
    ingest_window(client, payloads, app, start, end,
                  [(start, five, first_status), (five, end, other_status)])
    data = client.get("/api/review", params={"day": "2026-09-29"}).json()
    assert data["late_night_seconds"] == expected
    assert data["leisure_seconds"] == 3600


def test_manual_timing_and_classification_are_honored_at_five(app_context):
    client, app, payloads, _, _ = app_context
    start = datetime(2026, 9, 29, 4, tzinfo=BEIJING)
    five, end = start + timedelta(hours=1), start + timedelta(hours=2)
    ingest_window(client, payloads, app, start, end,
                  [(start, five, "afk"), (five, end, "not-afk")])
    events = client.get("/api/events").json()
    client.put("/api/events/timing", json={
        "event_ids": [events[0]["id"]], "policy": "foreground",
    }).raise_for_status()
    kept = client.get("/api/review?day=2026-09-29").json()
    assert kept["late_night_seconds"] == 3600 and kept["leisure_seconds"] == 7200
    client.put(f'/api/events/{events[0]["id"]}/override', json={
        "category": "work",
    }).raise_for_status()
    assert client.get("/api/review?day=2026-09-29").json()["late_night_seconds"] == 0


def test_longest_session_is_clipped_to_each_week(app_context):
    client, app, payloads, _, _ = app_context
    start = datetime(2026, 9, 27, 23, tzinfo=BEIJING)  # Sunday
    end = start + timedelta(hours=4)
    ingest_window(client, payloads, app, start, end, [(start, end, "not-afk")])
    previous = client.get("/api/review?day=2026-09-27").json()
    current = client.get("/api/review?day=2026-09-28").json()
    assert previous["longest_session"]["active_seconds"] == previous["leisure_seconds"] == 3600
    assert current["longest_session"]["active_seconds"] == current["leisure_seconds"] == 10800
    assert current["late_night_seconds"] == 10800
    assert datetime.fromisoformat(current["longest_session"]["start_time"]) == (
        start + timedelta(hours=1)
    )


def test_longest_keeps_start_of_session_when_the_first_day_was_afk(app_context):
    client, app, payloads, _, _ = app_context
    start = datetime(2026, 9, 28, 23, tzinfo=BEIJING)
    midnight, end = start + timedelta(hours=1), start + timedelta(hours=4)
    ingest_window(client, payloads, app, start, end,
                  [(start, midnight, "afk"), (midnight, end, "not-afk")])
    data = client.get("/api/review?day=2026-09-29").json()
    assert data["longest_session"]["active_seconds"] == 10800
    assert datetime.fromisoformat(data["longest_session"]["start_time"]) == start
