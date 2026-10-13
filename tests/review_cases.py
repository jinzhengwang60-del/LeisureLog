"""Review reproductions in isolated databases; no production writes."""

from datetime import datetime, timedelta, timezone

from leisurelog.adapters.playnite import CoverIndex
from leisurelog.domain.games import Game

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
