import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import select

from leisurelog.domain.models import ActivityEvent, SourceRecord
from leisurelog.repositories.library import SQLiteLibrary
from leisurelog.repositories.models import ContentAliasRow, ContentItemRow
from leisurelog.repositories.sqlite import SQLiteRepository
from tests.test_pipeline import START, WINDOW

pytest_plugins = ["tests.test_pipeline"]


def sync(client):
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()


def library(client):
    return client.get("/api/library").json()


def detail(client, item_id):
    response = client.get(f"/api/library/{item_id}")
    response.raise_for_status()
    return response.json()


def test_empty_catalog_and_scoped_named_content(app_context):
    client, _, payloads, _, _ = app_context
    assert library(client)["total"] == 0
    assert client.get("/library").status_code == 200
    payloads.append({**payloads[0], "id": 3, "data": {"app": "unknown.exe", "title": "测试"}})
    sync(client)
    result = library(client)
    assert result["total"] == 1
    assert result["items"][0]["name"] == "原神"
    assert result["active_seconds"] == 120
    key = result["items"][0]["id"]
    report = detail(client, key)
    assert report["item"]["days"] == 1
    assert report["item"]["sessions"] == 2  # The other app interrupts the game stream.
    assert report["item"]["recorded_seconds"] == 120
    assert report["aliases"][0]["app"] == "GenshinImpact.exe"
    assert result["items"][0]["apps"] == ["GenshinImpact.exe"]
    events = client.get("/api/events").json()
    other = next(e for e in events if e["app"] == "unknown.exe")
    client.put(
        f"/api/events/{other['id']}/override", json={"category": "game", "content": "原神"}
    ).raise_for_status()
    assert library(client)["total"] == 2  # Same name in another app is not guessed to be identical.
    client.put(
        f"/api/events/{other['id']}/override", json={"category": "reading", "content": "原神"}
    ).raise_for_status()
    assert library(client)["total"] == 3  # Dormant named content remains available.
    assert client.get("/api/library?category=reading").json()["total"] == 1


def test_rename_survives_rebuild_without_changing_records(app_context):
    client, app, _, _, _ = app_context
    sync(client)
    item_id = library(client)["items"][0]["id"]
    before = client.get("/api/events").json()
    edit = client.patch(f"/api/library/{item_id}", json={"name": " 我的原神 ", "notes": "长期记录"})
    edit.raise_for_status()
    for _ in range(2):
        client.post("/api/reprocess").raise_for_status()
    assert client.get("/api/events").json() == before
    assert detail(client, item_id)["item"]["name"] == "我的原神"
    assert (
        client.get("/api/library?query=原神").json()["total"] == 1
    )  # Original alias is searchable.
    assert client.get("/api/library?query=%25").json()["total"] == 0  # No wildcard expansion.
    with app.state.sessions() as db:
        assert len(list(db.scalars(select(ContentItemRow)))) == 1
        assert len(list(db.scalars(select(ContentAliasRow)))) == 1


def test_merge_split_and_future_alias_preserve_classification(app_context):
    client, _, payloads, _, _ = app_context
    sync(client)
    target = library(client)["items"][0]["id"]
    event_id = client.get("/api/events").json()[1]["id"]
    client.put(
        f"/api/events/{event_id}/override", json={"category": "game", "content": "Genshin"}
    ).raise_for_status()
    source = next(i["id"] for i in library(client)["items"] if i["name"] == "Genshin")
    client.patch(f"/api/library/{source}", json={"name": "另一个名称", "notes": "来源备注"})
    before = client.get("/api/events").json()
    merged = client.post(f"/api/library/{target}/merge", json={"source_id": source})
    merged.raise_for_status()
    assert library(client)["total"] == 1
    assert merged.json()["item"]["active_seconds"] == 120
    assert merged.json()["item"]["sessions"] == 2
    assert detail(client, source)["item"]["notes"] == "来源备注"
    assert detail(client, source)["item"]["active_seconds"] == 0
    client.post("/api/reprocess").raise_for_status()
    assert library(client)["total"] == 1
    assert client.get("/api/events").json() == before
    alias = next(a for a in detail(client, target)["aliases"] if a["name"] == "Genshin")
    split = client.post(f"/api/library/{target}/aliases/{alias['id']}/split")
    split.raise_for_status()
    assert split.json()["item"]["active_seconds"] == 60
    assert split.json()["item"]["id"] == source
    assert split.json()["item"]["name"] == "另一个名称"
    assert split.json()["item"]["notes"] == "来源备注"
    assert library(client)["total"] == 2
    assert detail(client, target)["item"]["active_seconds"] == 60
    new_id = split.json()["item"]["id"]
    client.post(f"/api/library/{target}/merge", json={"source_id": new_id}).raise_for_status()
    client.post(
        f"/api/library/{target}/aliases", json={"app": "GenshinImpact.exe", "name": "将来名称"}
    ).raise_for_status()
    payloads.append(
        {**payloads[0], "id": 3, "timestamp": (START + timedelta(minutes=5)).isoformat()}
    )
    sync(client)
    third = client.get("/api/events").json()[2]["id"]
    client.put(
        f"/api/events/{third}/override", json={"category": "game", "content": "将来名称"}
    ).raise_for_status()
    assert library(client)["total"] == 1
    assert detail(client, target)["item"]["active_seconds"] == 180
    assert detail(client, target)["item"]["days"] == 1


def test_cross_day_afk_timing_and_no_full_history_read(app_context, monkeypatch):
    client, app, payloads, _, _ = app_context
    start = START.replace(hour=15, minute=59)
    payloads[:] = [{**payloads[0], "timestamp": start.isoformat(), "duration": 120}]
    app.state.test_idle_payloads[:] = [
        {"id": 8, "timestamp": start.isoformat(), "duration": 120, "data": {"status": "afk"}},
    ]
    client.post(
        "/api/sync/activitywatch",
        json={
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=5)).isoformat(),
        },
    ).raise_for_status()
    key = library(client)["items"][0]["id"]
    assert detail(client, key)["item"]["active_seconds"] == 0
    event = client.get("/api/events").json()[0]["id"]
    client.put("/api/events/timing", json={"event_ids": [event], "policy": "foreground"})
    report = detail(client, key)
    assert report["item"]["days"] == 2 and report["item"]["sessions"] == 1
    assert report["item"]["active_seconds"] == report["item"]["retained_afk_seconds"] == 120
    assert report["item"]["afk_seconds"] == 0
    assert [day["active_seconds"] for day in report["days"]] == [60, 60]
    assert report["months"][0]["active_seconds"] == 120

    def forbidden(*args):
        raise AssertionError("Library queries must aggregate SQL, not load historical events")

    monkeypatch.setattr(SQLiteRepository, "events", forbidden)
    monkeypatch.setattr(SQLiteRepository, "sessions", forbidden)
    assert library(client)["active_seconds"] == 120
    report = client.get(f"/api/library/{key}?limit=1&offset=1").json()
    assert report["days"][0]["day"] == "2026-09-29"
    assert report["day_total"] == 2


@pytest.mark.parametrize(
    "suffix,method,body,status",
    [
        ("", "PATCH", {"name": "  "}, 422),
        ("", "PATCH", {"name": "a" * 301}, 422),
        ("", "PATCH", {"name": "ok", "notes": "a" * 2001}, 422),
        ("/merge", "POST", {"source_id": "missing"}, 404),
        ("/aliases", "POST", {"app": " ", "name": "test"}, 422),
        ("/aliases/missing/split", "POST", None, 404),
    ],
)
def test_invalid_edits_are_rejected(app_context, suffix, method, body, status):
    client, _, _, _, _ = app_context
    sync(client)
    key = library(client)["items"][0]["id"]
    before = detail(client, key)
    assert client.request(method, f"/api/library/{key}{suffix}", json=body).status_code == status
    assert detail(client, key) == before


def test_merge_scope_conflicts_and_atomicity(app_context, monkeypatch):
    client, _, _, _, _ = app_context
    sync(client)
    target = library(client)["items"][0]["id"]
    assert (
        client.post(f"/api/library/{target}/merge", json={"source_id": target}).status_code == 422
    )
    alias = detail(client, target)["aliases"][0]["id"]
    assert client.post(f"/api/library/{target}/aliases/{alias}/split").status_code == 422
    event_id = client.get("/api/events").json()[1]["id"]
    client.put(
        f"/api/events/{event_id}/override", json={"category": "reading", "content": "原神"}
    ).raise_for_status()
    source = client.get("/api/library?category=reading").json()["items"][0]["id"]
    assert (
        client.post(f"/api/library/{target}/merge", json={"source_id": source}).status_code == 422
    )
    client.put(
        f"/api/events/{event_id}/override", json={"category": "game", "content": "其他名"}
    ).raise_for_status()
    source = next(i["id"] for i in library(client)["items"] if i["name"] == "其他名")
    assert (
        client.post(
            f"/api/library/{target}/aliases", json={"app": "GenshinImpact.exe", "name": "其他名"}
        ).status_code
        == 422
    )
    before = library(client)

    def fail(*args):
        raise RuntimeError("detail read failed after write")

    with monkeypatch.context() as patch:
        patch.setattr(SQLiteLibrary, "detail", fail)
        with pytest.raises(RuntimeError, match="detail read failed"):
            client.post(f"/api/library/{target}/merge", json={"source_id": source})
    assert library(client) == before


def test_catalog_writes_roll_back_with_processing_failure(app_context, monkeypatch):
    client, app, _, _, _ = app_context

    def fail(*args):
        raise RuntimeError("derived write failed")

    monkeypatch.setattr(SQLiteRepository, "replace_daily", fail)
    with pytest.raises(RuntimeError, match="derived write failed"):
        sync(client)
    with app.state.sessions() as db:
        assert list(db.scalars(select(ContentItemRow))) == []
        assert list(db.scalars(select(ContentAliasRow))) == []


def test_library_migration_rebuild_and_backup_persistence(app_context):
    client, _, _, _, migration = app_context
    sync(client)
    key = library(client)["items"][0]["id"]
    client.patch(f"/api/library/{key}", json={"name": "备份名字", "notes": "备注"})
    client.post(f"/api/library/{key}/aliases", json={"app": "GenshinImpact.exe", "name": "别名"})
    backup = client.post("/api/storage/backups").json()
    directory = Path(client.get("/api/storage").json()["backup_directory"])
    with sqlite3.connect(directory / backup["name"]) as restored:
        assert restored.execute(
            "SELECT name,notes FROM content_items WHERE id=?", (key,)
        ).fetchone() == ("备份名字", "备注")
        assert restored.execute("SELECT count(*) FROM content_aliases").fetchone()[0] == 2
    report = json.loads((directory / backup["name"]).with_suffix(".json").read_text())
    assert report["verification"]["verified"]
    command.check(migration)
    command.downgrade(migration, "0007")
    assert client.get("/health").status_code == 503
    command.upgrade(migration, "head")
    client.post("/api/reprocess").raise_for_status()
    assert library(client)["items"][0]["name"] == "原神"
    assert library(client)["active_seconds"] == 120
    command.check(migration)


def test_bounded_list_pagination_literal_search_and_unknown_id(app_context):
    client, _, _, _, _ = app_context
    sync(client)
    key = library(client)["items"][0]["id"]
    assert client.get("/api/library?limit=101").status_code == 422
    assert client.get("/api/library?offset=-1").status_code == 422
    assert client.get("/api/library?sort=bad").status_code == 422
    assert client.get("/api/library/missing").status_code == 404
    assert client.get("/api/library?limit=1&offset=1").json()["items"] == []
    assert client.get("/api/library?query=_").json()["total"] == 0
    assert client.get("/api/library?sort=time").json()["items"][0]["id"] == key


def test_manual_cross_app_merge_keeps_days_distinct_and_apps_visible(app_context):
    client, _, payloads, _, _ = app_context
    payloads.append({**payloads[0], "id": 3, "data": {"app": "other.exe", "title": "原神"}})
    sync(client)
    target = library(client)["items"][0]["id"]
    event = next(e for e in client.get("/api/events").json() if e["app"] == "other.exe")
    client.put(
        f"/api/events/{event['id']}/override", json={"category": "game", "content": "原神"}
    ).raise_for_status()
    source = next(i["id"] for i in library(client)["items"] if i["id"] != target)
    before = client.get("/api/events").json()
    client.post(f"/api/library/{target}/merge", json={"source_id": source}).raise_for_status()
    client.post("/api/reprocess").raise_for_status()
    result = library(client)
    assert result["total"] == 1
    assert result["items"][0]["active_seconds"] == 180
    assert result["items"][0]["days"] == 1
    assert result["items"][0]["apps"] == ["GenshinImpact.exe", "other.exe"]
    assert result["items"][0]["alias_count"] == 2
    assert client.get("/api/events").json() == before


def test_multiple_years_day_pagination_and_recent_limit(app_context):
    client, app, _, _, _ = app_context
    with app.state.sessions() as db:
        repo = SQLiteRepository(db)
        for month in range(36):
            start = datetime(2023 + month // 12, month % 12 + 1, 1, tzinfo=timezone.utc)
            key = f"year-fixture-{month}"
            event = ActivityEvent(
                key,
                "fixture",
                "window",
                "pc",
                start,
                start + timedelta(seconds=60),
                "GenshinImpact.exe",
                "原神",
            )
            repo.ingest(SourceRecord(event, key, {"fixture": month}, {}))
        db.commit()
    client.post("/api/reprocess").raise_for_status()
    key = library(client)["items"][0]["id"]
    report = detail(client, key)
    assert report["item"]["days"] == report["item"]["sessions"] == 36
    assert report["item"]["active_seconds"] == 2160
    assert len(report["months"]) == 36
    assert len(report["days"]) == 30
    assert len(report["recent_sessions"]) == 20
    assert report["item"]["first_seen"].startswith("2023-01-01")
    assert report["item"]["last_seen"].startswith("2025-12-01")
    second = client.get(f"/api/library/{key}?offset=30").json()
    assert len(second["days"]) == 6
    assert second["days"][-1]["day"] == "2023-01-01"
