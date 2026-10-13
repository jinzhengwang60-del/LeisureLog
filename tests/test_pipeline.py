from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from leisurelog.adapters.activitywatch import ActivityWatchAdapter
from leisurelog.config import Settings
from leisurelog.domain.models import ActivityEvent
from leisurelog.domain.sessionization import merge_sessions
from leisurelog.main import create_app
from leisurelog.repositories.models import RawEventRow

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 9, 29, tzinfo=timezone.utc)
WINDOW = {"start": START.isoformat(), "end": (START + timedelta(hours=1)).isoformat()}


@pytest.fixture
def app_context(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "test.db").as_posix()
    monkeypatch.setenv("LEISURELOG_DATABASE_URL", url)
    migration = Config(str(ROOT / "alembic.ini"))
    command.upgrade(migration, "head")
    payloads = [
        {
            "id": 1,
            "timestamp": START.isoformat(),
            "duration": 60,
            "data": {"app": "GenshinImpact.exe", "title": "原神"},
        },
        {
            "id": 2,
            "timestamp": (START + timedelta(seconds=90)).isoformat(),
            "duration": 60,
            "data": {"app": "GenshinImpact.exe", "title": "原神"},
        },
    ]
    calls = []
    idle_payloads = []

    def respond(request):
        calls.append(request)
        if request.url.path == "/api/0/buckets/":
            return httpx.Response(
                200,
                json={
                    "window": {"type": "currentwindow", "hostname": "pc"},
                    "afk": {"type": "afkstatus", "hostname": "pc"},
                },
            )
        return httpx.Response(200, json=idle_payloads if "/afk/" in request.url.path else payloads)

    with httpx.Client(base_url="http://aw", transport=httpx.MockTransport(respond)) as upstream:
        app = create_app(
            Settings(
                database_url=url,
                rules_path=ROOT / "config/rules.yaml",
                auto_sync_enabled=False,
                auto_backup_days=0,
            ),
            source=ActivityWatchAdapter(upstream),
        )
        with TestClient(app) as client:
            app.state.test_idle_payloads = idle_payloads
            yield client, app, payloads, calls, migration


def test_sync_idempotent_revisions_overrides_and_rebuild(app_context):
    client, app, payloads, calls, _ = app_context
    assert client.get("/health").status_code == 200
    first = client.post("/api/sync/activitywatch", json=WINDOW)
    assert first.status_code == 200, first.text
    assert first.json() == {"fetched": 2, "changed": 2, "events": 2, "sessions": 1}
    session = client.get("/api/sessions").json()[0]
    assert session["active_seconds"] == 120  # 30-second gap excluded
    assert session["classification"]["category"] == "game"
    assert session["start_time"].endswith("+00:00")
    assert client.post("/api/sync/activitywatch", json=WINDOW).json()["changed"] == 0
    event_id = client.get("/api/events").json()[0]["id"]
    assert (
        client.put(f"/api/events/{event_id}/override", json={"category": "work"}).status_code == 200
    )
    payloads[0]["duration"] = 80
    assert client.post("/api/sync/activitywatch", json=WINDOW).json()["changed"] == 1
    assert client.post("/api/reprocess").status_code == 200
    events = client.get("/api/events").json()
    assert events[0]["classification"]["origin"] == "manual"
    assert events[0]["classification"]["category"] == "work"
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RawEventRow)) == 3
        assert db.get(RawEventRow, 1).payload["duration"] == 60
    assert client.delete(f"/api/events/{event_id}/override").status_code == 200
    assert client.get("/api/events").json()[0]["classification"]["category"] == "game"
    assert client.get("/api/stats/summary").json()["recorded_seconds_by_category"] == {"game": 140}
    assert all(r.url.params.get("limit") == "-1" for r in calls if "events" in r.url.path)


def test_failure_atomicity_and_validation(app_context):
    client, app, payloads, _, _ = app_context
    payloads.append({"broken": True})
    assert client.post("/api/sync/activitywatch", json=WINDOW).status_code == 502
    assert client.get("/api/events").json() == []
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RawEventRow)) == 0
    assert (
        client.post("/api/sync/activitywatch", json={**WINDOW, "start": "2026-09-29"}).status_code
        == 422
    )
    assert (
        client.post("/api/sync/activitywatch", json={**WINDOW, "end": WINDOW["start"]}).status_code
        == 422
    )
    assert (
        client.post("/api/sync/activitywatch", json={**WINDOW, "buckets": ["afk"]}).status_code
        == 502
    )
    assert client.get("/api/events?limit=1001").status_code == 422
    assert client.put("/api/events/missing/override", json={"category": "game"}).status_code == 404


def test_migration_roundtrip(app_context):
    client, _, _, _, migration = app_context
    command.check(migration)
    command.downgrade(migration, "base")
    assert client.get("/health").status_code == 503
    command.upgrade(migration, "head")
    assert client.get("/health").status_code == 200


def event(key, start, duration, app="game", device="pc"):
    return ActivityEvent(
        key,
        "test",
        "window",
        device,
        START + timedelta(seconds=start),
        START + timedelta(seconds=start + duration),
        app,
    )


def test_session_overlap_interruption_and_device_isolation():
    sessions = merge_sessions(
        [
            event("a", 0, 60),
            event("b", 30, 60),
            event("c", 95, 10, app="work"),
            event("d", 110, 10),
            event("e", 0, 60, device="other"),
            event("zero", 200, 0),
        ],
        60,
    )
    assert len(sessions) == 4
    assert sorted(s.active_seconds for s in sessions) == [10, 10, 60, 90]
    assert len(merge_sessions([event("a", 0, 10), event("b", 100, 10)], 60)) == 2


def test_upstream_connection_error(app_context):
    client, app, _, _, _ = app_context

    def fail(request):
        raise httpx.ConnectError("offline", request=request)

    with httpx.Client(base_url="http://aw", transport=httpx.MockTransport(fail)) as upstream:
        app.state.source = ActivityWatchAdapter(upstream)
        assert client.post("/api/sync/activitywatch", json=WINDOW).status_code == 502


def test_database_writes_roll_back_after_processing_failure(app_context, monkeypatch):
    from leisurelog.repositories.sqlite import SQLiteRepository

    client, app, payloads, _, _ = app_context
    assert client.post("/api/sync/activitywatch", json=WINDOW).status_code == 200
    before = client.get("/api/sessions").json()
    payloads[0]["duration"] = 75
    original = SQLiteRepository.replace_sessions

    def fail_after_replace(repo, sessions, scope=None):
        original(repo, sessions, scope)
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(SQLiteRepository, "replace_sessions", fail_after_replace)
    with pytest.raises(RuntimeError, match="simulated write failure"):
        client.post("/api/sync/activitywatch", json=WINDOW)
    assert client.get("/api/sessions").json() == before
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RawEventRow)) == 2


def test_bucket_update_does_not_revision_unchanged_events(app_context):
    from dataclasses import replace

    from leisurelog.repositories.sqlite import SQLiteRepository

    _, app, _, _, _ = app_context
    records = app.state.source.fetch(START, START + timedelta(hours=1), None)
    with app.state.sessions() as db:
        repo = SQLiteRepository(db)
        assert repo.ingest(records[0])
        updated = replace(records[0], metadata={**records[0].metadata, "last_updated": "later"})
        assert not repo.ingest(updated)
        assert db.scalar(select(func.count()).select_from(RawEventRow)) == 1


def test_automatic_sync_checkpoint_retry_and_restart(app_context):
    from threading import Event

    from leisurelog.adapters.activitywatch import SourceUnavailable
    from leisurelog.repositories.models import SyncCheckpointRow
    from leisurelog.runtime import AutomaticSync

    client, app, _, _, _ = app_context
    runner = AutomaticSync(
        app.state.sessions,
        app.state.source,
        app.state.pipeline,
        app.state.settings,
    )
    result = runner(Event())
    assert result["windows"] == 1
    with app.state.sessions() as db:
        previous_end = db.get(SyncCheckpointRow, "activitywatch").last_success_end

    class Offline:
        def fetch(self, *args):
            raise SourceUnavailable("offline")

    failing = AutomaticSync(
        app.state.sessions,
        Offline(),
        app.state.pipeline,
        app.state.settings,
    )
    with pytest.raises(SourceUnavailable):
        failing(Event())
    with app.state.sessions() as db:
        assert db.get(SyncCheckpointRow, "activitywatch").last_success_end == previous_end
        row = db.get(SyncCheckpointRow, "activitywatch")
        row.last_success_end = datetime.now(timezone.utc) - timedelta(days=2)
        db.commit()
    assert runner(Event())["windows"] == 3
    assert client.get("/api/sync/status").json()["enabled"] is False


def test_idle_ingestion_update_reprocess_and_manual_override(app_context):
    client, app, _, _, _ = app_context
    idle = app.state.test_idle_payloads
    idle.extend(
        [
            {
                "id": 10,
                "timestamp": START.isoformat(),
                "duration": 150,
                "data": {"status": "not-afk"},
            },
            {
                "id": 11,
                "timestamp": (START + timedelta(seconds=30)).isoformat(),
                "duration": 90,
                "data": {"status": "afk"},
            },
        ]
    )
    assert client.post("/api/sync/activitywatch", json=WINDOW).status_code == 200
    session = client.get("/api/sessions").json()[0]
    assert session["recorded_seconds"] == 120
    assert session["afk_seconds"] == 60
    assert session["active_seconds"] == 60
    assert session["unverified_seconds"] == 0
    assert len(client.get("/api/idle-events").json()) == 2
    assert client.post("/api/sync/activitywatch", json=WINDOW).json()["changed"] == 0
    idle[1]["duration"] = 120
    assert client.post("/api/sync/activitywatch", json=WINDOW).json()["changed"] == 1
    assert client.get("/api/sessions").json()[0]["active_seconds"] == 30
    event_id = client.get("/api/events").json()[0]["id"]
    client.put(f"/api/events/{event_id}/override", json={"category": "work"})
    assert client.post("/api/reprocess").status_code == 200
    assert client.get("/api/events").json()[0]["classification"]["origin"] == "manual"
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RawEventRow)) == 5


def test_bad_afk_data_rolls_back_entire_batch(app_context):
    client, app, _, _, _ = app_context
    app.state.test_idle_payloads.append(
        {"id": 5, "timestamp": START.isoformat(), "duration": 30, "data": {"status": "invalid"}}
    )
    assert client.post("/api/sync/activitywatch", json=WINDOW).status_code == 502
    assert client.get("/api/events").json() == []
    assert client.get("/api/idle-events").json() == []


def test_idle_migration_preserves_populated_sessions_and_raw_data(app_context):
    client, app, _, _, migration = app_context
    app.state.test_idle_payloads.append(
        {"id": 5, "timestamp": START.isoformat(), "duration": 60, "data": {"status": "afk"}}
    )
    assert client.post("/api/sync/activitywatch", json=WINDOW).status_code == 200
    assert client.get("/api/sessions").json()[0]["active_seconds"] == 60
    command.downgrade(migration, "0002")
    command.upgrade(migration, "head")
    session = client.get("/api/sessions").json()[0]
    assert session["recorded_seconds"] == 120
    assert session["active_seconds"] == 120
    assert session["unverified_seconds"] == 120
    assert len(session["event_ids"]) == 2
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RawEventRow)) == 3


def test_dashboard_filters_pagination_and_details(app_context):
    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW)
    result = client.get("/api/dashboard?day=2026-09-29&limit=1").json()
    assert result["total"] == 1
    assert result["items"][0]["recorded_seconds"] == 120
    assert result["options"]["apps"] == ["GenshinImpact.exe"]
    assert client.get("/api/dashboard?day=2026-09-29&app=missing").json()["total"] == 0
    assert client.get("/api/dashboard?day=2026-09-29&category=work").json()["total"] == 0
    assert client.get("/api/dashboard?day=2026-09-29&query=原神").json()["total"] == 1
    assert client.get("/api/dashboard?day=2026-09-29&offset=1").json()["items"] == []
    session_id = result["items"][0]["id"]
    details = client.get(f"/api/sessions/{session_id}/details?day=2026-09-29").json()
    assert len(details["events"]) == 2
    assert details["idle_events"] == []
    assert client.get(f"/api/sessions/{session_id}/details?day=2026-09-30").status_code == 404
    assert client.get("/api/dashboard?day=invalid").status_code == 422
    assert client.get("/api/dashboard?limit=1001").status_code == 422


def test_dashboard_midnight_clipping_recalculates_afk(app_context):
    from leisurelog.domain.models import IdleEvent, IdleSourceRecord, SourceRecord
    from leisurelog.repositories.sqlite import SQLiteRepository
    from leisurelog.services.processing import ProcessingService

    client, app, _, _, _ = app_context
    begin = datetime(2026, 9, 29, 15, 59, 30, tzinfo=timezone.utc)
    window = ActivityEvent(
        "midnight", "test", "window", "pc", begin, begin + timedelta(seconds=120), "game"
    )
    idle = IdleEvent(
        "idle",
        "test",
        "idle",
        "pc",
        begin + timedelta(seconds=30),
        begin + timedelta(seconds=60),
        "afk",
    )
    with app.state.sessions() as db:
        repo = SQLiteRepository(db)
        repo.ingest(SourceRecord(window, "window", {}, {}))
        repo.ingest(IdleSourceRecord(idle, "idle", {}, {}))
        ProcessingService(repo, app.state.pipeline, 60).rebuild()
        db.commit()
    yesterday = client.get("/api/dashboard?day=2026-09-29").json()["items"][0]
    today = client.get("/api/dashboard?day=2026-09-30").json()["items"][0]
    assert yesterday["recorded_seconds"] == 30
    assert yesterday["afk_seconds"] == 0
    assert today["recorded_seconds"] == 90
    assert today["afk_seconds"] == 30
    assert today["active_seconds"] == 60
    assert today["unverified_seconds"] == 60
    assert today["start_time"].startswith("2026-09-30T00:00:00")


def test_dashboard_serves_local_assets(app_context):
    client, _, _, _, _ = app_context
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "活动记录" in response.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_batch_classification_survives_sync_and_restores_rules(app_context):
    client, app, payloads, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW)
    ids = [e["id"] for e in client.get("/api/events").json()]
    body = {"event_ids": ids, "category": "reading", "content": "测试内容", "tags": ["漫画"]}
    result = client.put("/api/events/overrides", json=body)
    assert result.status_code == 200
    assert result.json()["updated"] == 2
    dashboard = client.get("/api/dashboard?day=2026-09-29&category=reading").json()
    assert dashboard["total"] == 1
    assert dashboard["summary"]["active_seconds_by_category"] == {"reading": 120}
    payloads[0]["duration"] = 80
    client.post("/api/sync/activitywatch", json=WINDOW)
    client.post("/api/reprocess")
    assert all(e["classification"]["origin"] == "manual" for e in client.get("/api/events").json())
    result = client.request("DELETE", "/api/events/overrides", json={"event_ids": ids})
    assert result.status_code == 200
    assert client.get("/api/sessions").json()[0]["classification"]["category"] == "game"
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RawEventRow)) == 3


def test_batch_missing_event_is_atomic_and_selection_validated(app_context):
    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW)
    event_id = client.get("/api/events").json()[0]["id"]
    body = {"event_ids": [event_id, "missing"], "category": "work"}
    assert client.put("/api/events/overrides", json=body).status_code == 404
    assert client.get("/api/events").json()[0]["classification"]["origin"].startswith("rule:")
    for selection in [[], [event_id, event_id], [""], ["x"] * 1001]:
        assert (
            client.put(
                "/api/events/overrides", json={"event_ids": selection, "category": "work"}
            ).status_code
            == 422
        )
    assert (
        client.put(
            "/api/events/overrides", json={"event_ids": [event_id], "category": ""}
        ).status_code
        == 422
    )


def test_batch_override_failure_rolls_back_every_event(app_context, monkeypatch):
    from leisurelog.repositories.sqlite import SQLiteRepository

    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW)
    ids = [e["id"] for e in client.get("/api/events").json()]
    original = SQLiteRepository.set_override

    def failing(repo, event_id, value):
        original(repo, event_id, value)
        if event_id == ids[-1]:
            raise RuntimeError("simulated failure")

    monkeypatch.setattr(SQLiteRepository, "set_override", failing)
    with pytest.raises(RuntimeError, match="simulated failure"):
        client.put("/api/events/overrides", json={"event_ids": ids, "category": "work"})
    assert all(
        e["classification"]["origin"].startswith("rule:") for e in client.get("/api/events").json()
    )
