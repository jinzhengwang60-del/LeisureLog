from datetime import datetime, timedelta, timezone

from leisurelog.analytics.grouping import group_sessions
from leisurelog.domain.models import Classification, Session
from tests.test_pipeline import START, WINDOW

pytest_plugins = ["tests.test_pipeline"]
T0 = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def session(ident, app, start, end, category="game", content="鸣潮", origin="rule:x"):
    seconds = float(end - start)
    return Session(
        ident, "aw", "s", "pc", app, f"{app} title", None,
        T0 + timedelta(seconds=start), T0 + timedelta(seconds=end), seconds,
        Classification(category, content, (), origin), [ident], seconds,
    )


def test_blocks_merge_same_activity_across_short_switches():
    blocks = group_sessions([
        session("a1", "Game.exe", 0, 600),
        session("w1", "Weixin.exe", 610, 640, "social", None),
        session("a2", "Game.exe", 660, 1200, origin="manual"),
        session("a3", "Game.exe", 1600, 1700),  # 400 s later: a new block
        session("b1", "Game.exe", 1710, 1800, content="原神"),  # different content
    ])
    shape = [(b["app"], b["classification"]["content"], b["session_count"]) for b in blocks]
    assert shape == [("Game.exe", "鸣潮", 2), ("Weixin.exe", None, 1),
                     ("Game.exe", "鸣潮", 1), ("Game.exe", "原神", 1)]
    first = blocks[0]
    # Times are summed, never the span (which would include the WeChat switch).
    assert first["recorded_seconds"] == 600 + 540
    assert first["active_seconds"] == 600 + 540
    assert first["start_time"] == T0 and first["end_time"] == T0 + timedelta(seconds=1200)
    assert first["classification"]["origin"] == "manual"
    assert [s["id"] for s in first["sessions"]] == ["a2", "a1"]


def test_dashboard_grouped_view_and_short_entries(app_context):
    client, _, payloads, _, _ = app_context
    payloads.append({"id": 3, "timestamp": (START + timedelta(minutes=10)).isoformat(),
                     "duration": 20, "data": {"app": "Weixin.exe", "title": "微信"}})
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    day = START.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    plain = client.get("/api/dashboard", params={"day": day}).json()
    grouped = client.get("/api/dashboard", params={"day": day, "view": "grouped"}).json()
    trimmed = client.get("/api/dashboard",
                         params={"day": day, "view": "grouped", "min_seconds": 60}).json()
    assert plain["view"] == "sessions" and "kind" not in plain["items"][0]
    assert all(item["kind"] == "group" for item in grouped["items"])
    assert sum(i["session_count"] for i in grouped["items"]) == plain["total"]
    # The 20-second WeChat entry is hidden from the list but still in the summary.
    assert trimmed["hidden_short"] == 1
    assert all(i["app"] != "Weixin.exe" for i in trimmed["items"])
    assert trimmed["summary"] == grouped["summary"] == plain["summary"]
    assert client.get("/api/dashboard", params={"day": day, "view": "x"}).status_code == 422


def test_hour_grid_spreads_time_and_limits_range(app_context):
    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    day = START.astimezone(timezone(timedelta(hours=8))).date()
    data = client.get("/api/statistics/hours",
                      params={"start": day.isoformat(), "end": day.isoformat()}).json()
    hours = data["days"][0]["hours"]
    assert len(hours) == 24
    # START is 08:00 in Beijing; both one-minute Genshin events fall in that hour.
    assert hours[8]["top"] == "game" and round(hours[8]["active_seconds"]) == 120
    assert sum(h["active_seconds"] for h in hours) == hours[8]["active_seconds"]
    wide = client.get("/api/statistics/hours",
                      params={"start": "2026-01-01", "end": day.isoformat()}).json()
    assert wide["truncated"] is True and len(wide["days"]) == 31
    assert wide["days"][-1]["day"] == day.isoformat()
    backwards = {"start": day.isoformat(), "end": "2026-01-01"}
    assert client.get("/api/statistics/hours", params=backwards).status_code == 422
