import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import select

from leisurelog.adapters.playnite import parse_export
from leisurelog.domain.models import ActivityEvent, SourceRecord
from leisurelog.repositories.games import SQLiteGameCatalog
from leisurelog.repositories.models import GameCatalogRow
from leisurelog.repositories.sqlite import SQLiteRepository
from tests.test_games import catalog, game
from tests.test_pipeline import WINDOW

pytest_plugins = ["tests.test_pipeline"]


def named(app, name):
    return "named:" + json.dumps([app, name], ensure_ascii=False, separators=(",", ":"))


def listing(client, **params):
    response = client.get("/api/game-statistics", params=params)
    response.raise_for_status()
    return response.json()


def detail(client, key, **params):
    response = client.get("/api/game-statistics/" + quote(key, safe=""), params=params)
    response.raise_for_status()
    return response.json()


def install(app, *rows):
    with app.state.sessions() as db:
        SQLiteGameCatalog(db).replace(catalog(*rows), parse_export(catalog(*rows)))
        db.commit()


def test_catalog_is_not_playtime_and_pagination_validation(app_context):
    client, app, _, _, _ = app_context
    assert listing(client)["total"] == 0
    row = game()
    install(app, row, game("未安装", installed=False))
    result = listing(client)
    assert result["total"] == 1
    assert result["active_seconds"] == 0 and result["recorded_games"] == 0
    report = detail(client, "playnite:" + row["id"])
    assert report["item"]["last_seen"] is None
    assert report["days"] == report["months"] == report["recent_sessions"] == []
    assert listing(client, scope="recorded")["total"] == 0
    assert listing(client, scope="all", limit=1, offset=1)["items"][0]["name"] == "未安装"
    assert listing(client, query="%_")["total"] == 0
    for params in ({"scope": "bad"}, {"limit": 101}, {"offset": -1}, {"sort": "bad"}):
        assert client.get("/api/game-statistics", params=params).status_code == 422
    assert client.get("/api/game-statistics/missing").status_code == 404
    assert client.get("/games").status_code == 200


def test_unique_name_rules_manual_changes_and_ambiguous_names(app_context):
    client, app, _, _, _ = app_context
    row = game()
    install(app, row)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    report = detail(client, "playnite:" + row["id"])
    assert report["item"]["recorded_seconds"] == 120  # 30 second gap is not counted.
    assert report["item"]["sessions"] == 1
    session = report["recent_sessions"][0]
    assert (
        client.get(
            f"/api/sessions/{session['id']}/details", params={"day": session["day"]}
        ).status_code
        == 200
    )
    for event in client.get("/api/events").json():
        client.put(
            f"/api/events/{event['id']}/override", json={"category": "work"}
        ).raise_for_status()
    assert detail(client, "playnite:" + row["id"])["item"]["recorded_seconds"] == 0
    for event in client.get("/api/events").json():
        client.delete(f"/api/events/{event['id']}/override").raise_for_status()
    install(app, row, game())  # Same catalog title: do not assign one record to both IDs.
    result = listing(client, scope="recorded")
    assert result["total"] == 1 and result["items"][0]["key"] == named("GenshinImpact.exe", "原神")
    assert result["active_seconds"] == 120


def test_sdk_id_survives_catalog_rename_and_removal(app_context):
    client, app, payloads, _, _ = app_context
    row = game()
    install(app, row)
    for payload in payloads:
        payload["data"]["app"] = "YuanShen.exe"
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    key = "playnite:" + row["id"]
    assert detail(client, key)["item"]["active_seconds"] == 120
    install(app, {**row, "name": "原神新名称"})
    assert detail(client, key)["item"]["name"] == "原神新名称"
    assert detail(client, key)["item"]["active_seconds"] == 120
    install(app)  # Read-only stats preserve observed facts even without a current catalog row.
    assert detail(client, key)["item"]["in_catalog"] is False
    assert listing(client)["total"] == 1


def test_unmatched_same_title_in_different_apps_is_not_guessed(app_context):
    client, _, payloads, _, _ = app_context
    for payload, app in zip(payloads, ("first.exe", "second.exe"), strict=True):
        payload["data"]["app"] = app
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    events = client.get("/api/events").json()
    client.put(
        "/api/events/overrides",
        json={"event_ids": [e["id"] for e in events], "category": "game", "content": "同名游戏"},
    ).raise_for_status()
    report = listing(client)
    assert report["total"] == 2 and report["active_seconds"] == 120
    assert {i["app"] for i in report["items"]} == {"first.exe", "second.exe"}
    assert {i["active_seconds"] for i in report["items"]} == {60}


def test_cross_midnight_afk_daily_allocation_and_single_session(app_context):
    client, app, payloads, _, _ = app_context
    idle = app.state.test_idle_payloads
    start = datetime(2026, 9, 29, 15, 59, 30, tzinfo=timezone.utc)
    payloads[:] = [
        {
            "id": 9,
            "timestamp": start.isoformat(),
            "duration": 120,
            "data": {"app": "GenshinImpact.exe", "title": "原神"},
        }
    ]
    idle[:] = [
        {"id": 1, "timestamp": start.isoformat(), "duration": 45, "data": {"status": "afk"}},
        {
            "id": 2,
            "timestamp": (start + timedelta(seconds=45)).isoformat(),
            "duration": 75,
            "data": {"status": "not-afk"},
        },
    ]
    client.post(
        "/api/sync/activitywatch",
        json={"start": start.isoformat(), "end": (start + timedelta(minutes=3)).isoformat()},
    ).raise_for_status()
    report = detail(client, named("GenshinImpact.exe", "原神"))
    assert report["item"]["recorded_seconds"] == 120
    assert report["item"]["active_seconds"] == 75
    assert report["item"]["afk_seconds"] == 45
    assert report["item"]["sessions"] == len(report["recent_sessions"]) == 1
    assert report["item"]["days"] == 2
    days = {d["day"]: d for d in report["days"]}
    assert days["2026-09-29"]["recorded_seconds"] == 30
    assert days["2026-09-29"]["active_seconds"] == 0
    assert days["2026-09-30"]["recorded_seconds"] == 90
    assert days["2026-09-30"]["active_seconds"] == 75
    assert (
        detail(client, named("GenshinImpact.exe", "原神"), limit=1, offset=1)["days"][0]["day"]
        == "2026-09-29"
    )


def test_years_of_history_and_non_catalog_game_name_with_slash(app_context):
    client, app, _, _, _ = app_context
    with app.state.sessions() as db:
        repo = SQLiteRepository(db)
        for index in range(36):
            start = datetime(2023 + index // 12, index % 12 + 1, 1, tzinfo=timezone.utc)
            event = ActivityEvent(
                str(index),
                "test",
                "window",
                "pc",
                start,
                start + timedelta(seconds=60),
                "custom.exe",
                "自定义游戏",
            )
            repo.ingest(SourceRecord(event, str(index), {"index": index}, {}))
        db.commit()
    # A remembered rule classifies all events consistently without a Playnite catalog.
    client.post("/api/reprocess").raise_for_status()
    events = client.get("/api/events", params={"limit": 100}).json()
    client.put(
        "/api/events/overrides",
        json={"event_ids": [e["id"] for e in events], "category": "game", "content": "游戏/特别版"},
    ).raise_for_status()
    report = detail(client, named("custom.exe", "游戏/特别版"), limit=30)
    assert report["item"]["days"] == report["item"]["sessions"] == 36
    assert report["item"]["active_seconds"] == 2160
    assert len(report["months"]) == 36 and len(report["days"]) == 30
    assert len(report["recent_sessions"]) == 20
    assert len(detail(client, named("custom.exe", "游戏/特别版"), offset=30)["days"]) == 6
    assert listing(client, scope="recorded", query="特别")["total"] == 1
    with app.state.sessions() as db:
        assert list(db.scalars(select(GameCatalogRow))) == []
