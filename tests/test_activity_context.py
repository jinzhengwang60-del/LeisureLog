"""Independent purpose and project attribution through migrations, processing and reports."""

import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from leisurelog.adapters.rules import RuleClassifier
from leisurelog.config import Settings
from leisurelog.domain.activity_context import CategoryPurposeClassifier, resolve_context
from leisurelog.domain.browser import resolve_browser
from leisurelog.domain.models import ActivityEvent, Classification
from leisurelog.main import create_app
from leisurelog.repositories.models import ContextOverrideRow, ContextRuleRow, RawEventRow
from leisurelog.repositories.sqlite import SQLiteRepository
from leisurelog.repositories.storage import connect_readonly, fingerprint, verify_restore
from tests.test_browser import add_page, page
from tests.test_pipeline import ROOT, START, WINDOW
from tests.test_unclassified import add

pytest_plugins = ["tests.test_pipeline"]
RANGE = {"start": "2026-09-29", "end": "2026-09-29"}


def create_project(client, name="LeisureLog", **values):
    response = client.post("/api/projects", json={"name": name, **values})
    response.raise_for_status()
    return response.json()


def attribute(client, ids, **values):
    response = client.put("/api/events/context", json={"event_ids": ids, **values})
    response.raise_for_status()
    return response.json()


def events(client):
    return client.get("/api/events").json()


def raw_facts(app):
    with app.state.sessions() as db:
        return [(r.id, r.payload) for r in db.scalars(select(RawEventRow).order_by(RawEventRow.id))]


@pytest.mark.parametrize(
    "category,purpose",
    [
        ("game", "leisure"),
        ("work", "work"),
        ("study", "study"),
        ("create", "create"),
        ("social", "communication"),
        ("system", "system"),
        ("video", "unknown"),
        ("reading", "unknown"),
        ("coding", "unknown"),
        ("office", "unknown"),
    ],
)
def test_conservative_purposes_are_independent_of_activity_type(category, purpose):
    event = ActivityEvent(
        "one",
        "aw",
        "window",
        "pc",
        START,
        START + timedelta(minutes=1),
        "app",
        classification=Classification(category),
    )
    resolved = resolve_browser([event], [])[0]
    context = resolve_context(resolved, [CategoryPurposeClassifier()], {})
    assert context.purpose == purpose
    assert context.project_id is None
    assert resolved.classification.category == category


def test_manual_fields_split_sessions_preserve_raw_and_restore_independently(app_context):
    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    before = raw_facts(app)
    first, second = events(client)
    project = create_project(client)
    attribute(client, [first["id"]], purpose="work", project_id=project["id"])
    selected = events(client)[0]
    assert selected["classification"] == first["classification"]
    assert selected["context"] == {
        "purpose": "work",
        "project_id": project["id"],
        "purpose_origin": "manual",
        "project_origin": "manual",
    }
    assert len(client.get("/api/sessions").json()) == 2
    assert (
        client.get("/api/dashboard", params={"day": RANGE["start"], "view": "grouped"}).json()[
            "total"
        ]
        == 2
    )
    attribute(client, [first["id"]], purpose=None)
    assert events(client)[0]["context"]["purpose"] == "leisure"
    assert events(client)[0]["context"]["project_id"] == project["id"]
    attribute(client, [second["id"]], purpose="study")
    client.put(f"/api/events/{second['id']}/override", json={"category": "work"}).raise_for_status()
    assert events(client)[1]["context"]["purpose"] == "study"
    client.post("/api/reprocess").raise_for_status()
    assert events(client)[1]["context"]["purpose_origin"] == "manual"
    client.request(
        "DELETE", "/api/events/context", json={"event_ids": [first["id"]]}
    ).raise_for_status()
    assert events(client)[0]["context"]["project_id"] is None
    assert raw_facts(app) == before


def test_partial_learned_rules_future_import_manual_priority_and_deletion(app_context):
    client, _, payloads, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    project = create_project(client)
    event_id = events(client)[0]["id"]
    attribute(client, [event_id], purpose="study", remember_scope="app")
    attribute(client, [event_id], project_id=project["id"], remember_scope="app")
    rules = client.get("/api/activity-context/rules").json()
    assert len(rules) == 1
    assert rules[0]["assignments"] == {"purpose": "study", "project_id": project["id"]}
    assert events(client)[1]["context"]["purpose_origin"] == "learned"
    attribute(client, [events(client)[1]["id"]], purpose="leisure", project_id=None)
    add(payloads, 3, 240, "GenshinImpact.exe", "原神", 90)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    assert events(client)[2]["context"]["project_id"] == project["id"]
    assert events(client)[2]["context"]["purpose"] == "study"
    assert events(client)[1]["context"]["project_id"] is None
    client.request(
        "DELETE", "/api/events/context", json={"event_ids": [event_id]}
    ).raise_for_status()
    assert events(client)[0]["context"]["purpose_origin"] == "learned"
    client.delete(f"/api/activity-context/rules/{rules[0]['id']}").raise_for_status()
    assert events(client)[0]["context"]["project_id"] is None
    assert events(client)[0]["context"]["purpose"] == "leisure"
    assert events(client)[1]["context"]["project_origin"] == "manual"


def test_browser_segments_inherit_window_choice_but_can_restore_one_segment(app_context):
    client, app, payloads, _, _ = app_context
    payloads[:] = [
        {
            **payloads[0],
            "duration": 120,
            "data": {"app": "msedge.exe", "title": "测试页面 - Microsoft Edge"},
        }
    ]
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    raw_id = events(client)[0]["id"]
    project = create_project(client)
    attribute(client, [raw_id], purpose="work", project_id=project["id"])
    add_page(app, page("course", start=0, duration=60))
    add_page(app, page("other", start=60, duration=60, url="https://www.bilibili.com/video/second"))
    client.post("/api/reprocess").raise_for_status()
    first, second = events(client)
    assert all(e["context"]["project_id"] == project["id"] for e in (first, second))
    attribute(client, [first["id"]], purpose="study", project_id=None)
    client.request(
        "DELETE", "/api/events/context", json={"event_ids": [first["id"]]}
    ).raise_for_status()
    assert events(client)[0]["context"]["purpose"] == "unknown"
    assert events(client)[0]["context"]["project_id"] is None
    assert events(client)[1]["context"]["purpose"] == "work"
    with app.state.sessions() as db:
        assert db.get(ContextOverrideRow, raw_id).assignments["purpose"] == "work"


def test_browser_rules_specific_scope_and_invalid_bulk_requests_are_atomic(app_context):
    client, app, payloads, _, _ = app_context
    payloads[:] = [
        {
            **payloads[0],
            "duration": 120,
            "data": {"app": "msedge.exe", "title": "测试页面 - Microsoft Edge"},
        }
    ]
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    add_page(app, page(start=0, duration=120))
    client.post("/api/reprocess").raise_for_status()
    before = events(client)
    event_id = before[0]["id"]
    for values, status in [
        ({"purpose": "study", "remember_scope": "app"}, 422),
        ({"project_id": "missing", "purpose": "work"}, 404),
        ({"purpose": "nope"}, 422),
        ({}, 422),
        ({"purpose": None, "remember_scope": "domain"}, 422),
    ]:
        result = client.put("/api/events/context", json={"event_ids": [event_id], **values})
        assert result.status_code == status
        assert events(client) == before
    result = client.put(
        "/api/events/context", json={"event_ids": [event_id, "missing"], "purpose": "work"}
    )
    assert result.status_code == 404
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ContextOverrideRow)) == 0
        assert db.scalar(select(func.count()).select_from(ContextRuleRow)) == 0
    attribute(client, [event_id], purpose="study", remember_scope="domain")
    attribute(client, [event_id], purpose="leisure", remember_scope="url")
    client.request(
        "DELETE", "/api/events/context", json={"event_ids": [event_id]}
    ).raise_for_status()
    assert events(client)[0]["context"]["purpose"] == "leisure"
    rules = client.get("/api/activity-context/rules").json()
    url_rule = next(rule for rule in rules if rule["scope"] == "url")
    client.delete(f"/api/activity-context/rules/{url_rule['id']}").raise_for_status()
    assert events(client)[0]["context"]["purpose"] == "study"


def test_project_reports_filters_and_weekly_review_include_all_purposes(app_context, monkeypatch):
    client, _, payloads, _, _ = app_context
    add(payloads, 3, 300, "Code.exe", "LeisureLog", 180)
    add(payloads, 4, 600, "msedge.exe", "课程_哔哩哔哩_bilibili", 120)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    project = create_project(client)
    ids = [e["id"] for e in events(client)]
    attribute(client, [ids[2]], purpose="work", project_id=project["id"])
    attribute(client, [ids[3]], purpose="study", project_id=project["id"])
    report = client.get("/api/projects", params=RANGE).json()
    assert report["totals"]["active_seconds"] == 420
    assert report["unassigned_seconds"] == 120
    assert report["items"][0]["active_seconds"] == 300
    detail = client.get(f"/api/projects/{project['id']}", params=RANGE).json()
    assert detail["totals"]["active_seconds"] == 300
    assert {row["app"] for row in detail["apps"]} == {"Code.exe", "msedge.exe"}
    assert detail["days"][0]["active_seconds"] == 300
    statistics = client.get(
        "/api/statistics", params={**RANGE, "project_id": project["id"], "purpose": "study"}
    ).json()
    assert statistics["totals"]["active_seconds"] == 120
    assert statistics["purposes"][0]["purpose"] == "study"
    assert statistics["totals"]["purpose_unknown_seconds"] == 0
    dashboard = client.get(
        "/api/dashboard",
        params={"day": RANGE["start"], "project_id": project["id"], "purpose": "study"},
    ).json()
    assert dashboard["total"] == 1
    assert dashboard["highlights"]["activity_seconds"] == 420
    assert dashboard["highlights"]["purpose_seconds"]["work"] == 180
    hours = client.get(
        "/api/statistics/hours", params={**RANGE, "project_id": project["id"], "purpose": "study"}
    ).json()
    assert sum(h["active_seconds"] for d in hours["days"] for h in d["hours"]) == 120
    review = client.get("/api/review", params={"day": RANGE["start"]}).json()
    assert review["activity_seconds"] == 420
    assert review["purpose_seconds"] == {"leisure": 120, "work": 180, "study": 120}
    assert review["project_count"] == 1
    assert len(review["all_top_activities"]) == 3

    # Project reports use bounded SQL facts, not full object histories.
    def no_history(*args, **kwargs):
        raise AssertionError("Project reports must read calendar facts through SQL")

    monkeypatch.setattr(SQLiteRepository, "events", no_history)
    monkeypatch.setattr(SQLiteRepository, "sessions", no_history)
    assert client.get("/api/projects", params=RANGE).status_code == 200


def test_rename_archive_preserves_history_and_rules_and_validates_fields(app_context):
    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    project = create_project(client)
    attribute(client, [events(client)[0]["id"]], project_id=project["id"], remember_scope="app")
    update = {"name": "新名称", "description": "已完成", "color": "#10b981", "archived": True}
    client.put(f"/api/projects/{project['id']}", json=update).raise_for_status()
    report = client.get("/api/projects", params=RANGE).json()
    assert report["items"][0]["name"] == "新名称"
    assert report["items"][0]["archived"] is True
    assert report["items"][0]["active_seconds"] == 120
    client.post("/api/reprocess").raise_for_status()
    assert all(e["context"]["project_id"] == project["id"] for e in events(client))
    assert len(client.get("/api/activity-context/rules").json()) == 1
    for body in [
        {"name": " "},
        {"name": "x", "color": "url(javascript:test)"},
        {"name": "x", "extra": 1},
    ]:
        assert client.post("/api/projects", json=body).status_code == 422
    assert client.put("/api/projects/missing", json={"name": "x"}).status_code == 404
    assert client.get("/api/projects/missing", params=RANGE).status_code == 404
    assert client.get("/api/projects", params={**RANGE, "end": "2026-09-28"}).status_code == 422


def test_context_failure_rolls_back_rules_manual_choices_and_processed_state(
    app_context, monkeypatch
):
    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    project = create_project(client)
    before = events(client)
    original = SQLiteRepository.replace_daily

    def fail(self, facts, scope=None):
        original(self, facts, scope)
        raise RuntimeError("failed after new facts were written")

    monkeypatch.setattr(SQLiteRepository, "replace_daily", fail)
    with pytest.raises(RuntimeError, match="failed after"):
        attribute(
            client,
            [before[0]["id"]],
            purpose="work",
            project_id=project["id"],
            remember_scope="app",
        )
    assert events(client) == before
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ContextOverrideRow)) == 0
        assert db.scalar(select(func.count()).select_from(ContextRuleRow)) == 0


def test_config_purpose_reload_preserves_manual_choices_and_rejects_invalid(tmp_path, app_context):
    client, app, payloads, _, _ = app_context
    add(payloads, 3, 300, "anki.exe", "卡片", 90)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    assert events(client)[2]["context"]["purpose"] == "study"
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "rules: []\npurpose_rules: [{id: anki, match: {app: anki.exe}, purpose: work}]\n",
        encoding="utf-8",
    )
    app.state.settings.rules_path = rules_path
    client.post("/api/classification/reload-rules").raise_for_status()
    assert events(client)[2]["context"]["purpose"] == "work"
    attribute(client, [events(client)[2]["id"]], purpose="study")
    client.post("/api/classification/reload-rules").raise_for_status()
    assert events(client)[2]["context"]["purpose"] == "study"
    rules_path.write_text(
        "rules: []\npurpose_rules: [{id: bad, match: {app: anki.exe}, purpose: invalid}]\n",
        encoding="utf-8",
    )
    assert client.post("/api/classification/reload-rules").status_code == 422
    assert events(client)[2]["context"]["purpose"] == "study"
    with pytest.raises(ValueError):
        RuleClassifier(rules_path)


def test_cross_midnight_project_facts_keep_exact_active_time(app_context):
    client, app, payloads, _, _ = app_context
    start = datetime(2026, 9, 29, 15, 59, tzinfo=timezone.utc)
    payloads[:] = [{**payloads[0], "timestamp": start.isoformat(), "duration": 120}]
    app.state.test_idle_payloads[:] = [
        {"id": 9, "timestamp": start.isoformat(), "duration": 120, "data": {"status": "not-afk"}},
        {
            "id": 10,
            "timestamp": (start + timedelta(seconds=30)).isoformat(),
            "duration": 90,
            "data": {"status": "afk"},
        },
    ]
    client.post(
        "/api/sync/activitywatch",
        json={"start": start.isoformat(), "end": (start + timedelta(minutes=5)).isoformat()},
    ).raise_for_status()
    project = create_project(client)
    attribute(client, [events(client)[0]["id"]], purpose="work", project_id=project["id"])
    result = client.get(
        f"/api/projects/{project['id']}", params={**RANGE, "end": "2026-09-30"}
    ).json()
    assert result["totals"]["active_seconds"] == 30
    assert result["totals"]["recorded_seconds"] == 120
    assert [row["active_seconds"] for row in result["days"]] == [30, 0]


def test_migration_backup_restore_with_projects_and_original_corrections(app_context, tmp_path):
    client, app, _, _, migration = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    raw_before = raw_facts(app)
    event_id = events(client)[0]["id"]
    client.put(f"/api/events/{event_id}/override", json={"category": "work"}).raise_for_status()
    project = create_project(client)
    attribute(client, [event_id], purpose="study", project_id=project["id"], remember_scope="app")
    command.check(migration)
    backup = client.post("/api/storage/backups").json()
    assert backup["counts"]["activity_projects"] == 1
    assert backup["counts"]["context_overrides"] == 1
    assert backup["counts"]["context_rules"] == 1
    restored = tmp_path / "restored.db"
    restored.write_bytes(client.get(backup["download_url"]).content)
    assert verify_restore(restored)["database_revision"] == "0013"
    with TestClient(
        create_app(
            Settings(
                database_url="sqlite:///" + restored.as_posix(),
                rules_path=ROOT / "config/rules.yaml",
                auto_sync_enabled=False,
                auto_backup_days=0,
            )
        )
    ) as recovered:
        assert (
            recovered.get("/api/activity-context/options").json()
            == client.get("/api/activity-context/options").json()
        )
        assert recovered.get("/api/events").json() == events(client)
        recovered.post("/api/reprocess").raise_for_status()
        assert recovered.get("/api/events").json() == events(client)
    command.downgrade(migration, "0011")
    assert client.get("/health").status_code == 503
    command.upgrade(migration, "head")
    client.post("/api/reprocess").raise_for_status()
    assert events(client)[0]["classification"]["origin"] == "manual"
    assert raw_facts(app) == raw_before
    assert client.get("/api/activity-context/options").json()["projects"] == []
    with connect_readonly(Path(app.state.storage.store.database)) as db:
        assert "context_overrides" in fingerprint(db)


def test_keyword_rules_follow_changed_titles_and_are_narrower_than_app_rules(app_context):
    client, _, payloads, _, _ = app_context
    add(payloads, 3, 300, "Code.exe", "main.py - LeisureLog", 90)
    add(payloads, 4, 600, "Code.exe", "notes.md - AnotherProject", 90)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    broad, specific = create_project(client, "日常开发"), create_project(client, "LeisureLog")
    event_id = events(client)[2]["id"]
    attribute(client, [event_id], project_id=broad["id"], remember_scope="app")
    attribute(
        client,
        [event_id],
        project_id=specific["id"],
        purpose="work",
        remember_scope="title_contains",
        match_text=" LeisureLog ",
    )
    add(payloads, 5, 900, "Code.exe", "PROJECTS.md - LEISURELOG", 120)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    latest = events(client)[4]
    assert latest["context"]["project_id"] == specific["id"]
    assert latest["context"]["purpose_origin"] == "learned"
    assert events(client)[3]["context"]["project_id"] == broad["id"]
    attribute(client, [latest["id"]], project_id=None)
    client.post("/api/reprocess").raise_for_status()
    assert events(client)[4]["context"]["project_id"] is None


@pytest.mark.parametrize("text", ["x", "  ", "missing keyword"])
def test_invalid_keyword_rule_leaves_choices_unchanged(app_context, text):
    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    before = events(client)
    result = client.put(
        "/api/events/context",
        json={
            "event_ids": [before[0]["id"]],
            "purpose": "work",
            "remember_scope": "title_contains",
            "match_text": text,
        },
    )
    assert result.status_code == 422
    assert events(client) == before
    assert client.get("/api/activity-context/rules").json() == []


def test_csv_export_matches_filtered_statistics_and_has_no_activity_titles(app_context):
    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    project = create_project(client, "=unsafe name")
    attribute(client, [events(client)[0]["id"]], purpose="study", project_id=project["id"])
    response = client.get("/api/statistics/export", params={**RANGE, "project_id": project["id"]})
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
    assert rows[1][0:2] == ["2026-09-29", "是"]
    assert float(rows[1][2]) == 60
    assert len(rows[0]) == len(rows[1]) == 8
    assert "=unsafe name" not in response.text
    assert "原神" not in response.text
    assert "attachment" in response.headers["content-disposition"]
    assert (
        client.get("/api/statistics/export", params={**RANGE, "end": "2026-09-28"}).status_code
        == 422
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/dashboard",
        "/api/dashboard/ribbon",
        "/api/statistics",
        "/api/statistics/hours",
        "/api/statistics/export",
    ],
)
def test_report_filters_reject_invalid_purposes(app_context, path):
    client, _, _, _, _ = app_context
    assert client.get(path, params={**RANGE, "purpose": "invented"}).status_code == 422


def test_zero_activity_and_new_page_assets_do_not_invent_projects(app_context):
    client, _, _, _, _ = app_context
    result = client.get("/api/projects", params=RANGE).json()
    assert result["items"] == []
    assert result["totals"]["active_seconds"] == result["unassigned_seconds"] == 0
    for path in [
        "/projects",
        "/static/projects.js",
        "/static/activity-context.js",
        "/static/activity-context.css",
        "/static/report-ui.js",
    ]:
        assert client.get(path).status_code == 200


def test_success_response_is_sent_after_project_commit(app_context):
    _, app, _, _, _ = app_context
    observed = []

    class ObserveResponse:
        async def __call__(self, scope, receive, send):
            async def observe(message):
                if message["type"] == "http.response.start" and message["status"] == 201:
                    # A separate WAL reader sees only committed rows. Inspect at
                    # the moment the browser can receive a successful response.
                    with connect_readonly(app.state.storage.store.database) as db:
                        observed.append(db.execute("SELECT name FROM activity_projects").fetchall())
                await send(message)
            await app(scope, receive, observe)

    observer = TestClient(ObserveResponse())
    try:
        response = observer.post("/api/projects", json={"name": "已提交的项目"})
        assert response.status_code == 201
        assert observed == [[("已提交的项目",)]]
        assert response.headers["cache-control"] == "no-store"
    finally:
        observer.close()
