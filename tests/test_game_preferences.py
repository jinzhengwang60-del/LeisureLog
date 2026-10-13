from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select

from leisurelog.config import Settings
from leisurelog.domain.game_types import canonical_tags, resolve_game_type
from leisurelog.domain.models import ActivityEvent, Classification, SourceRecord
from leisurelog.main import create_app
from leisurelog.repositories.game_preferences import SQLiteGamePreferences
from leisurelog.repositories.models import GameTypeOverrideRow, IdleEventRow, RawEventRow
from leisurelog.repositories.sqlite import SQLiteRepository
from tests.test_game_statistics import detail, install, named
from tests.test_games import game
from tests.test_pipeline import WINDOW

pytest_plugins = ["tests.test_pipeline"]


def report(client, start="2026-01-01", end="2026-12-31"):
    response = client.get("/api/game-preferences", params={"start": start, "end": end})
    response.raise_for_status()
    return response.json()


def save(client, key, primary="strategy", tags=None):
    return client.put(
        "/api/game-types/" + quote(key, safe=""),
        json={"primary": primary, "tags": ["开放世界"] if tags is None else tags},
    )


def test_vocabulary_is_exact_deduplicated_and_does_not_guess_names():
    assert canonical_tags([" RPG ", "Role-playing (RPG)", "ｒｐｇ", "Indie", "独立游戏"])
    assert canonical_tags([" RPG ", "Role-playing (RPG)", "ｒｐｇ"]) == ["角色扮演"]
    assert resolve_game_type(["RPG", "ARPG", "Indie", "open-world"])["primary"] == "arpg"
    assert resolve_game_type(["Strategy", "Card & Board Game"])["primary"] == "card"
    assert resolve_game_type(["RPG-ish", "原神", "独立游戏"])["primary"] == "unknown"
    assert resolve_game_type(["RPG"], {"primary": "unknown", "tags": []})["source"] == "manual"


def test_manual_choices_preserve_source_and_survive_import_reprocess_restart(app_context):
    client, app, payloads, _, _ = app_context
    row = game()
    install(app, row)
    for payload in payloads:
        payload["data"]["app"] = "YuanShen.exe"
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    key = "playnite:" + row["id"]
    original = detail(client, key)
    with app.state.sessions() as db:
        raw_before = [r.payload for r in db.scalars(select(RawEventRow).order_by(RawEventRow.id))]
    changed = save(client, key, "card", ["indie", "独立游戏", "自己的标签"]).json()
    assert changed["item"]["game_type"]["tags"] == ["独立游戏", "自己的标签"]
    assert changed["item"]["game_type"]["source"] == "manual"
    assert changed["item"]["active_seconds"] == original["item"]["active_seconds"]
    assert changed["recent_sessions"] == original["recent_sessions"]
    renamed = {**row, "name": "新的名称", "tags": ["Racing"]}
    install(app, renamed)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    client.post("/api/reprocess").raise_for_status()
    result = detail(client, key)["item"]
    assert result["game_type"]["primary"] == "card"
    assert result["game_type"]["automatic_primary"] == "racing"
    assert result["tags"] == ["Racing"]
    with app.state.sessions() as db:
        assert [
            r.payload for r in db.scalars(select(RawEventRow).order_by(RawEventRow.id))
        ] == raw_before
    settings = Settings(
        database_url=app.state.settings.database_url,
        rules_path=app.state.settings.rules_path,
        auto_sync_enabled=False,
        auto_backup_days=0,
    )
    with TestClient(create_app(settings)) as restarted:
        assert detail(restarted, key)["item"]["game_type"]["primary"] == "card"
        assert report(restarted)["types"][0]["primary"] == "card"
    response = client.delete("/api/game-types/" + quote(key, safe=""))
    assert response.json()["item"]["game_type"]["primary"] == "racing"
    assert response.json()["item"]["game_type"]["source"] == "automatic"


def test_removed_catalog_retains_manual_choice_and_same_name_apps_stay_separate(app_context):
    client, app, payloads, _, _ = app_context
    row = game()
    install(app, row)
    for payload in payloads:
        payload["data"]["app"] = "YuanShen.exe"
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    key = "playnite:" + row["id"]
    save(client, key, "puzzle").raise_for_status()
    install(app)
    assert detail(client, key)["item"]["game_type"]["primary"] == "puzzle"
    assert report(client)["types"][0]["primary"] == "puzzle"
    install(app, row)
    assert detail(client, key)["item"]["game_type"]["source"] == "manual"
    # Separate fallback keys have separate manual metadata, even with equal names.
    for payload, exe in zip(payloads, ("first.exe", "second.exe"), strict=True):
        payload["data"]["app"] = exe
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    ids = [e["id"] for e in client.get("/api/events").json()]
    client.put(
        "/api/events/overrides", json={"event_ids": ids, "category": "game", "content": "同名"}
    ).raise_for_status()
    save(client, named("first.exe", "同名"), "sports").raise_for_status()
    assert detail(client, named("second.exe", "同名"))["item"]["game_type"]["primary"] == "unknown"


def ingest(app, rows):
    with app.state.sessions() as db:
        repo = SQLiteRepository(db)
        for index, (exe, start, seconds, category, content) in enumerate(rows):
            event = ActivityEvent(
                f"pref-{index}",
                "fixture",
                "window",
                "pc",
                start,
                start + timedelta(seconds=seconds),
                exe,
                content or exe,
            )
            repo.ingest(SourceRecord(event, event.id, {"index": index}, {}))
            if category:
                repo.set_override(event.id, Classification(category, content, (), "manual"))
        db.commit()


def test_cross_year_months_afk_unnamed_and_multitag_time_conservation(app_context):
    client, app, _, _, _ = app_context
    a, b, c = game("A", r"D:\A.exe"), game("B", r"D:\B.exe"), game("C", r"D:\C.exe")
    a["tags"] = ["RPG", "ARPG", "Indie", "RPG"]
    b["tags"] = ["Strategy", "Card & Board Game"]
    c["tags"] = []
    install(app, a, b, c)
    midnight = datetime(2023, 12, 31, 15, 59, 30, tzinfo=timezone.utc)
    jan = datetime(2024, 1, 20, tzinfo=timezone.utc)
    ingest(
        app,
        [
            ("A.exe", midnight, 120, None, None),
            ("B.exe", jan, 60, None, None),
            ("C.exe", jan, 30, None, None),
            ("no-name.exe", jan, 40, "game", None),
            ("work.exe", jan, 50, "work", "工作"),
        ],
    )
    with app.state.sessions() as db:
        # Timing coverage only applies to the cross-year activity.
        for index, (offset, length, status) in enumerate([(0, 45, "afk"), (45, 75, "not-afk")]):
            raw = db.scalar(select(RawEventRow).where(RawEventRow.event_id == "pref-0"))
            db.add(
                IdleEventRow(
                    id=f"pref-idle-{index}",
                    raw_event_id=raw.id,
                    source="fixture",
                    stream="idle",
                    device="pc",
                    start_time=midnight + timedelta(seconds=offset),
                    end_time=midnight + timedelta(seconds=offset + length),
                    status=status,
                )
            )
        db.commit()
    client.post("/api/reprocess").raise_for_status()
    result = report(client, "2024-01-01", "2024-12-31")
    assert result["totals"]["active_seconds"] == 205
    assert result["totals"]["recorded_seconds"] == 220
    assert result["totals"]["afk_seconds"] == 15
    assert result["totals"]["unverified_seconds"] == 130
    assert result["untyped_seconds"] == 70 and result["unnamed_seconds"] == 40
    assert result["recorded_games"] == 3
    types = {t["primary"]: t for t in result["types"]}
    assert {k: v["active_seconds"] for k, v in types.items()} == {
        "arpg": 75,
        "card": 60,
        "unknown": 70,
    }
    assert sum(t["active_seconds"] for t in types.values()) == 205
    assert sum(t["share"] for t in types.values()) == pytest.approx(1)
    assert len(result["trend"]) == 12
    assert result["trend"][0]["has_game_records"]
    assert result["trend"][1]["has_activity_records"] is False
    assert result["coverage"]["game_days"] == 2
    partial = report(client, "2023-12-31", "2024-01-01")
    assert partial["totals"]["active_seconds"] == 75
    assert partial["trend"][0]["active_seconds"] == 0
    assert partial["trend"][0]["has_game_records"]
    assert partial["trend"][0]["types"][0]["share"] is None
    assert partial["trend"][1]["active_seconds"] == 75
    save(client, "playnite:" + a["id"], "strategy", ["开放世界", "独立游戏"]).raise_for_status()
    updated = report(client, "2024-01-01", "2024-12-31")
    assert updated["totals"] == result["totals"]
    assert updated["trend"][0]["types"][0]["primary"] == "strategy"


def test_empty_no_game_and_validation(app_context):
    client, app, _, _, _ = app_context
    result = report(client)
    assert result["totals"]["active_seconds"] == 0 and result["types"] == []
    assert len(result["trend"]) == 12
    assert all(not m["has_activity_records"] for m in result["trend"])
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    ingest(app, [("work.exe", start, 60, "work", "工作")])
    client.post("/api/reprocess").raise_for_status()
    result = report(client)
    assert result["trend"][2]["has_activity_records"] and not result["trend"][2]["has_game_records"]
    assert client.get("/game-preferences").status_code == 200
    assert client.get("/api/game-types").json()["types"]
    for start, end in [
        ("2026-03-02", "2026-03-01"),
        ("2000-01-01", "2026-01-01"),
        ("9999-01-01", "9999-01-31"),
    ]:
        assert (
            client.get("/api/game-preferences", params={"start": start, "end": end}).status_code
            == 422
        )
    row = game()
    install(app, row)
    key = "playnite:" + row["id"]
    for primary, tags in [("bad", []), ("rpg", [""]), ("rpg", ["x" * 81]), ("rpg", ["x"] * 51)]:
        assert save(client, key, primary, tags).status_code == 422
    assert save(client, "missing").status_code == 404
    assert client.delete("/api/game-types/missing").status_code == 404
    assert detail(client, key)["item"]["game_type"]["source"] == "automatic"


def test_write_failure_rolls_back_type_choice(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    row = game()
    install(app, row)
    key = "playnite:" + row["id"]
    save(client, key, "rpg").raise_for_status()

    def fail(*args, **kwargs):
        raise RuntimeError("response lookup failed")

    monkeypatch.setattr(SQLiteGamePreferences, "detail", fail)
    with pytest.raises(RuntimeError, match="lookup failed"):
        save(client, key, "card")
    with app.state.sessions() as db:
        assert db.get(GameTypeOverrideRow, key).primary_type == "rpg"


def test_three_year_trend_uses_aggregates_without_loading_all_events(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    row = game("长期游戏", r"D:\LongGame.exe")
    install(app, row)
    rows = [
        (
            "LongGame.exe",
            datetime(2023 + i // 12, i % 12 + 1, 1, tzinfo=timezone.utc),
            60,
            None,
            None,
        )
        for i in range(36)
    ]
    ingest(app, rows)
    client.post("/api/reprocess").raise_for_status()

    def fail(*args, **kwargs):
        raise AssertionError("All-history objects must not be loaded for analytics")

    monkeypatch.setattr(SQLiteRepository, "events", fail)
    monkeypatch.setattr(SQLiteRepository, "sessions", fail)
    result = report(client, "2023-01-01", "2025-12-31")
    assert result["totals"]["active_seconds"] == 2160
    assert result["recorded_games"] == 1
    assert result["coverage"]["game_days"] == 36
    assert len(result["trend"]) == 36
    assert all(month["has_game_records"] for month in result["trend"])
    assert all(month["types"][0]["primary"] == "rpg" for month in result["trend"])
    assert result["types"][0]["share"] == 1


def test_migration_roundtrip_and_backup_restore(app_context, tmp_path):
    client, app, _, _, migration = app_context
    row = game()
    install(app, row)
    key = "playnite:" + row["id"]
    save(client, key, "puzzle", ["自己的标签"]).raise_for_status()
    backup = client.post("/api/storage/backups").json()
    assert backup["counts"]["game_type_overrides"] == 1
    restored = tmp_path / "restored.db"
    restored.write_bytes(client.get(backup["download_url"]).content)
    with TestClient(
        create_app(
            Settings(
                database_url="sqlite:///" + restored.as_posix(),
                rules_path=app.state.settings.rules_path,
                auto_sync_enabled=False,
                auto_backup_days=0,
            )
        )
    ) as recovered:
        assert recovered.get("/health").json()["database_revision"] == "0013"
        assert detail(recovered, key)["item"]["game_type"]["tags"] == ["自己的标签"]
    command.downgrade(migration, "0009")
    command.upgrade(migration, "head")
    assert detail(client, key)["item"]["game_type"]["source"] == "automatic"
    assert client.get("/health").json()["database_revision"] == "0013"
