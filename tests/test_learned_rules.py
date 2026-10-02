from dataclasses import replace
from datetime import datetime, timezone

import pytest
from alembic import command
from sqlalchemy import func, select

from leisurelog.domain.learned_rules import LearnedRuleClassifier, remember
from leisurelog.domain.models import ActivityEvent, Classification
from leisurelog.repositories.models import LearnedRuleRow, RawEventRow
from tests.test_pipeline import WINDOW

pytest_plugins = ["tests.test_pipeline"]


def test_remember_future_import_manual_priority_and_delete(app_context):
    client, app, payloads, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    ids = [e["id"] for e in client.get("/api/events").json()]
    body = {"event_ids": [ids[0]], "category": "work", "remember_scope": "app"}
    assert client.put("/api/events/overrides", json=body).status_code == 200
    events = client.get("/api/events").json()
    assert events[0]["classification"]["origin"] == "manual"
    assert events[1]["classification"]["origin"] == "learned"
    # An event arriving later uses the stored rule without another correction.
    payloads.append(
        {**payloads[1], "id": 3, "data": {"app": "GenshinImpact.exe", "title": "新标题"}}
    )
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    events = client.get("/api/events").json()
    future = next(e for e in events if e["title"] == "新标题")
    assert future["classification"]["category"] == "work"
    assert future["classification"]["origin"] == "learned"
    # Independent manual decisions outrank learned rules.
    client.put(
        f"/api/events/{future['id']}/override", json={"category": "music"}
    ).raise_for_status()
    client.post("/api/reprocess").raise_for_status()
    rule = client.get("/api/classification/rules").json()[0]
    assert client.delete(f"/api/classification/rules/{rule['id']}").status_code == 200
    events = client.get("/api/events").json()
    assert next(e for e in events if e["id"] == ids[1])["classification"]["category"] == "game"
    assert (
        next(e for e in events if e["id"] == future["id"])["classification"]["category"] == "music"
    )
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RawEventRow)) == 3


def test_rule_upsert_restore_and_restart_persistence(app_context):
    client, _, _, _, migration = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    ids = [e["id"] for e in client.get("/api/events").json()]
    body = {"event_ids": ids, "category": "work", "remember_scope": "title"}
    client.put("/api/events/overrides", json=body).raise_for_status()
    client.put("/api/events/overrides", json={**body, "category": "video"}).raise_for_status()
    assert len(client.get("/api/classification/rules").json()) == 1
    client.request("DELETE", "/api/events/overrides", json={"event_ids": ids}).raise_for_status()
    assert all(e["classification"]["origin"] == "learned" for e in client.get("/api/events").json())
    # Running the upgrade again must preserve rules, and a new app reads them from SQLite.
    command.upgrade(migration, "head")
    from fastapi.testclient import TestClient

    from leisurelog.main import create_app

    with TestClient(create_app(client.app.state.settings)) as restarted:
        restarted.post("/api/reprocess").raise_for_status()
        assert all(
            e["classification"]["category"] == "video" for e in restarted.get("/api/events").json()
        )


def test_invalid_scope_atomic_and_migration_roundtrip(app_context, monkeypatch):
    client, app, payloads, _, migration = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    ids = [e["id"] for e in client.get("/api/events").json()]
    body = {"event_ids": ids, "category": "work", "remember_scope": "domain"}
    assert client.put("/api/events/overrides", json=body).status_code == 422
    payloads[1]["data"]["title"] = "不同标题"
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    assert (
        client.put("/api/events/overrides", json={**body, "remember_scope": "title"}).status_code
        == 422
    )
    assert client.get("/api/classification/rules").json() == []
    assert all(e["classification"]["origin"] != "manual" for e in client.get("/api/events").json())
    from leisurelog.repositories.sqlite import SQLiteRepository

    def fail(*args):
        raise RuntimeError("simulated failure after saving rule")

    with monkeypatch.context() as patch:
        patch.setattr(SQLiteRepository, "replace_sessions", fail)
        with pytest.raises(RuntimeError):
            client.put("/api/events/overrides", json={**body, "remember_scope": "app"})
    assert client.get("/api/classification/rules").json() == []
    client.put("/api/events/overrides", json={**body, "remember_scope": "app"}).raise_for_status()
    command.downgrade(migration, "0003")
    command.upgrade(migration, "head")
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(LearnedRuleRow)) == 0
        assert db.scalar(select(func.count()).select_from(RawEventRow)) == 3
    assert all(e["classification"]["origin"] == "manual" for e in client.get("/api/events").json())


def test_specific_scope_and_domain_boundaries():
    now = datetime.now(timezone.utc)
    event = ActivityEvent(
        "1", "aw", "window", "pc", now, now, "chrome.exe", "电影", "https://example.com/a"
    )
    app = remember([event], "app", Classification(category="browsing"))
    title = remember([event], "title", Classification(category="film"))
    domain = remember([event], "domain", Classification(category="video"))
    assert LearnedRuleClassifier([app, title]).classify(event).category == "film"
    classifier = LearnedRuleClassifier([domain, app])
    assert classifier.classify(replace(event, url="https://EXAMPLE.com/b")).category == "video"
    assert (
        classifier.classify(replace(event, url="https://sub.example.com/b")).category == "browsing"
    )
    assert classifier.classify(replace(event, app="edge.exe")) is None
    assert classifier.classify(replace(event, source="another")) is None
    assert LearnedRuleClassifier([title]).classify(replace(event, title="电影 2")) is None


def test_malformed_url_does_not_stop_classification():
    now = datetime.now(timezone.utc)
    event = ActivityEvent(
        "1", "aw", "window", "pc", now, now, "chrome.exe", "title", "https://example.com"
    )
    rule = remember([event], "domain", Classification(category="video"))
    assert LearnedRuleClassifier([rule]).classify(replace(event, url="http://[invalid")) is None
