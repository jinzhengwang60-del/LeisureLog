"""Purpose confirmation, non-mutating previews, explanations and reversible decisions."""

from datetime import timedelta

import pytest
from alembic import command
from sqlalchemy import func, select

from leisurelog.repositories.models import ContextChangeRow, ContextOverrideRow, ContextRuleRow
from leisurelog.repositories.sqlite import SQLiteRepository
from tests.test_activity_context import RANGE, attribute, create_project, events, raw_facts
from tests.test_browser import add_page, page
from tests.test_pipeline import START, WINDOW
from tests.test_unclassified import add

pytest_plugins = ["tests.test_pipeline"]


def preview(client, ids, **values):
    result = client.post("/api/activity-context/preview", json={"event_ids": ids, **values})
    result.raise_for_status()
    return result.json()


def test_preview_is_read_only_predicts_changes_and_protects_other_manual_choices(app_context):
    client, app, payloads, _, _ = app_context
    add(payloads, 3, 240, "GenshinImpact.exe", "原神", 60)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    first, second, third = events(client)
    attribute(client, [second["id"]], purpose="work")
    before, raw_before = events(client), raw_facts(app)
    rule = {"purpose": "study", "remember_scope": "app"}
    result = preview(client, [first["id"]], **rule)
    assert result["matched_events"] == 3
    assert result["changed_events"] == 2
    assert result["manual_protected_events"] == 1
    assert result["scope"] == "all_history"
    assert events(client) == before
    assert client.get("/api/activity-context/rules").json() == []
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ContextChangeRow)) == 1
    saved = attribute(client, [first["id"]], **rule, preview_token=result["preview_token"])
    assert saved["change_id"]
    after = events(client)
    assert [e["context"]["purpose"] for e in after] == ["study", "work", "study"]
    assert (
        sum(a["context"]["purpose"] != b["context"]["purpose"] for a, b in zip(before, after))
        == result["changed_events"]
    )
    assert raw_facts(app) == raw_before
    assert after[2]["id"] == third["id"]


def test_changed_preview_rejects_without_writing_then_accepts_a_new_preview(app_context):
    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    first, second = events(client)
    body = {"event_ids": [first["id"]], "purpose": "study", "remember_scope": "app"}
    old = client.post("/api/activity-context/preview", json=body).json()
    attribute(client, [second["id"]], purpose="work")
    before = events(client)
    response = client.put(
        "/api/events/context", json={**body, "preview_token": old["preview_token"]}
    )
    assert response.status_code == 409
    assert events(client) == before
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ContextRuleRow)) == 0
        assert db.scalar(select(func.count()).select_from(ContextOverrideRow)) == 1
    fresh = client.post("/api/activity-context/preview", json=body).json()
    assert fresh["preview_token"] != old["preview_token"]
    assert (
        client.put(
            "/api/events/context", json={**body, "preview_token": fresh["preview_token"]}
        ).status_code
        == 200
    )


def test_keyword_preview_honors_unicode_and_more_specific_rules(app_context):
    client, _, payloads, _, _ = app_context
    payloads[:] = []
    add(payloads, 1, 0, "Code.exe", "Straße - 项目", 60)
    add(payloads, 2, 90, "CODE.EXE", "STRASSE - 项目", 60)
    add(payloads, 3, 180, "Code.exe", "另一个项目", 60)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    first, second, _ = events(client)
    attribute(client, [second["id"]], purpose="create", remember_scope="title")
    client.request(
        "DELETE", "/api/events/context", json={"event_ids": [second["id"]]}
    ).raise_for_status()
    result = preview(
        client, [first["id"]], purpose="work", remember_scope="title_contains", match_text="STRASSE"
    )
    assert result["matched_events"] == 2
    assert result["changed_events"] == 1
    assert result["manual_protected_events"] == 0
    attribute(
        client,
        [first["id"]],
        purpose="work",
        remember_scope="title_contains",
        match_text="STRASSE",
        preview_token=result["preview_token"],
    )
    assert events(client)[1]["context"]["purpose"] == "create"


@pytest.mark.parametrize("scope,matched", [("domain", 2), ("url", 1)])
def test_web_preview_canonicalizes_host_and_fragments(app_context, scope, matched):
    client, app, payloads, _, _ = app_context
    payloads[:] = [
        {**payloads[0], "duration": 180, "data": {"app": "msedge.exe", "title": "测试页面 - Edge"}}
    ]
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    add_page(app, page("one", start=0, duration=60, url="https://WWW.BILIBILI.COM/video/one#t=10"))
    add_page(app, page("two", start=60, duration=60, url="https://www.bilibili.com/video/two"))
    add_page(app, page("other", start=120, duration=60, url="https://example.org/"))
    client.post("/api/reprocess").raise_for_status()
    result = preview(client, [events(client)[0]["id"]], purpose="study", remember_scope=scope)
    assert result["matched_events"] == matched
    assert result["changed_events"] == matched


def test_pending_groups_use_active_calendar_facts_and_keep_pages_bounded(app_context, monkeypatch):
    client, app, payloads, _, _ = app_context
    payloads[:] = []
    add(payloads, 1, 0, "Code.exe", "文件 A", 60)
    add(payloads, 2, 90, "CODE.EXE", "文件 B", 120)
    add(payloads, 3, 300, "GenshinImpact.exe", "原神", 90)
    add(payloads, 4, 600, "editor.exe", "完全离开", 60)
    app.state.test_idle_payloads[:] = [
        {
            "id": 90,
            "timestamp": (START + timedelta(seconds=600)).isoformat(),
            "duration": 60,
            "data": {"status": "afk"},
        }
    ]
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()

    def no_history(*args, **kwargs):
        raise AssertionError("Confirmation summaries must not load the whole history")

    monkeypatch.setattr(SQLiteRepository, "events", no_history)
    monkeypatch.setattr(SQLiteRepository, "sessions", no_history)
    result = client.get("/api/activity-context/pending", params=RANGE).json()
    assert result["groups"] == 1
    assert result["active_seconds"] == 180
    group = result["items"][0]
    assert group["app"] == "code.exe" and not group["browser"]
    assert group["days"] == 1 and group["sessions"] == 2
    rows = client.get(
        "/api/activity-context/pending/events",
        params={**RANGE, "source": group["source"], "app": group["app"], "limit": 1},
    ).json()
    assert rows["total_events"] == 2 and len(rows["items"]) == 1
    assert (
        client.get("/api/activity-context/pending", params={**RANGE, "search": "CODE"}).json()[
            "groups"
        ]
        == 1
    )
    assert (
        client.get("/api/activity-context/pending", params={**RANGE, "search": "%"}).json()[
            "groups"
        ]
        == 0
    )
    assert (
        client.get("/api/activity-context/pending", params={**RANGE, "offset": 1}).json()["items"]
        == []
    )


def test_pending_groups_split_browser_websites_and_ignore_confirmed_purposes(app_context):
    client, app, payloads, _, _ = app_context
    payloads[:] = [
        {**payloads[0], "duration": 180, "data": {"app": "msedge.exe", "title": "测试页面 - Edge"}}
    ]
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    add_page(app, page("one", start=0, duration=60, url="https://www.bilibili.com/video/one"))
    add_page(app, page("two", start=60, duration=60, url="https://example.org/"))
    add_page(app, page("three", start=120, duration=60, url="https://www.bilibili.com/video/three"))
    client.post("/api/reprocess").raise_for_status()
    attribute(client, [events(client)[2]["id"]], purpose="study")
    result = client.get("/api/activity-context/pending", params=RANGE).json()
    assert result["groups"] == 2 and result["active_seconds"] == 120
    assert all(row["browser"] for row in result["items"])
    group = next(row for row in result["items"] if row["website"] == "www.bilibili.com")
    selected = client.get(
        "/api/activity-context/pending/events",
        params={
            **RANGE,
            "source": group["source"],
            "app": group["app"],
            "website": group["website"],
        },
    ).json()
    assert selected["total_events"] == 1
    attribute(client, [selected["items"][0]["id"]], purpose="leisure")
    assert client.get("/api/activity-context/pending", params=RANGE).json()["groups"] == 1


def test_undo_remembered_rule_restores_previous_overrides_and_future_processing(app_context):
    client, app, payloads, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    first = events(client)[0]["id"]
    attribute(client, [first], purpose="work")
    original, raw_before = events(client), raw_facts(app)
    project = create_project(client)
    saved = attribute(
        client, [first], purpose="study", project_id=project["id"], remember_scope="app"
    )
    add(payloads, 3, 240, "GenshinImpact.exe", "原神", 60)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    response = client.post(f"/api/activity-context/changes/{saved['change_id']}/undo")
    assert response.status_code == 200
    after = events(client)
    assert after[:2] == original
    assert after[2]["context"]["purpose"] == "leisure"
    assert after[2]["context"]["project_id"] is None
    assert client.get("/api/activity-context/rules").json() == []
    assert raw_facts(app)[: len(raw_before)] == raw_before
    assert (
        client.post(f"/api/activity-context/changes/{saved['change_id']}/undo").status_code == 409
    )
    history = client.get("/api/activity-context/changes").json()
    assert history["items"][0]["undone_at"]
    assert "before" not in history["items"][0]


def test_undo_conflict_preserves_newer_choice_until_it_is_undone(app_context):
    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    first = events(client)[0]["id"]
    earlier = attribute(client, [first], purpose="work")
    later = attribute(client, [first], purpose="study")
    before = events(client)
    assert (
        client.post(f"/api/activity-context/changes/{earlier['change_id']}/undo").status_code == 409
    )
    assert events(client) == before
    client.post(f"/api/activity-context/changes/{later['change_id']}/undo").raise_for_status()
    client.post(f"/api/activity-context/changes/{earlier['change_id']}/undo").raise_for_status()
    assert events(client)[0]["context"]["purpose"] == "leisure"
    assert client.post("/api/activity-context/changes/missing/undo").status_code == 404


def test_rule_deletion_can_be_undone_without_touching_manual_choices(app_context):
    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    first = events(client)[0]["id"]
    attribute(client, [first], purpose="study", remember_scope="app")
    before = events(client)
    rule = client.get("/api/activity-context/rules").json()[0]
    deletion = client.delete(f"/api/activity-context/rules/{rule['id']}").json()
    assert events(client)[1]["context"]["purpose"] == "leisure"
    client.post(f"/api/activity-context/changes/{deletion['change_id']}/undo").raise_for_status()
    assert events(client) == before


def test_restoring_a_deleted_rule_preserves_its_original_precedence(app_context):
    client, _, payloads, _, _ = app_context
    payloads[:] = []
    add(payloads, 1, 0, "Code.exe", "AABB", 60)
    add(payloads, 2, 90, "Code.exe", "AABB", 60)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    first = events(client)[0]["id"]
    attribute(client, [first], purpose="work", remember_scope="title_contains", match_text="AA")
    attribute(client, [first], purpose="study", remember_scope="title_contains", match_text="BB")
    client.request("DELETE", "/api/events/context", json={"event_ids": [first]}).raise_for_status()
    old = next(
        rule for rule in client.get("/api/activity-context/rules").json() if rule["value"] == "aa"
    )
    before = events(client)
    assert all(event["context"]["purpose"] == "study" for event in before)
    deletion = client.delete(f"/api/activity-context/rules/{old['id']}").json()
    client.post(f"/api/activity-context/changes/{deletion['change_id']}/undo").raise_for_status()
    assert events(client) == before


def test_undo_window_attribution_after_browser_segments_have_changed(app_context):
    client, app, payloads, _, _ = app_context
    payloads[:] = [
        {**payloads[0], "duration": 120, "data": {"app": "msedge.exe", "title": "测试页面 - Edge"}}
    ]
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    original_id = events(client)[0]["id"]
    saved = attribute(client, [original_id], purpose="work")
    add_page(app, page("first", start=0, duration=60))
    add_page(
        app, page("second", start=60, duration=60, url="https://www.bilibili.com/video/second")
    )
    client.post("/api/reprocess").raise_for_status()
    assert all(e["id"] != original_id and e["context"]["purpose"] == "work" for e in events(client))
    client.post(f"/api/activity-context/changes/{saved['change_id']}/undo").raise_for_status()
    assert len(events(client)) == 2
    assert all(e["context"]["purpose"] == "unknown" for e in events(client))


def test_preview_streams_more_than_one_batch_without_truncating_impact(app_context):
    client, _, payloads, _, _ = app_context
    payloads[:] = []
    for index in range(300):
        add(payloads, index + 1, index * 10, "Code.exe", f"项目 - 文件 {index}", 5)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    first = events(client)[0]["id"]
    result = preview(client, [first], purpose="work", remember_scope="app")
    assert result["matched_events"] == result["changed_events"] == 300
    assert len(result["samples"]) == 6


def test_pending_cross_midnight_uses_actual_active_intervals(app_context):
    client, app, payloads, _, _ = app_context
    begin = START.replace(hour=15, minute=59)
    payloads[:] = [
        {
            **payloads[0],
            "timestamp": begin.isoformat(),
            "duration": 120,
            "data": {"app": "Code.exe", "title": "项目"},
        }
    ]
    app.state.test_idle_payloads[:] = [
        {
            "id": 90,
            "timestamp": (begin + timedelta(seconds=30)).isoformat(),
            "duration": 90,
            "data": {"status": "afk"},
        }
    ]
    client.post(
        "/api/sync/activitywatch",
        json={"start": begin.isoformat(), "end": (begin + timedelta(minutes=3)).isoformat()},
    ).raise_for_status()
    first_day = client.get("/api/activity-context/pending", params=RANGE).json()
    assert first_day["active_seconds"] == 30 and first_day["groups"] == 1
    assert (
        client.get(
            "/api/activity-context/pending", params={"start": "2026-09-30", "end": "2026-09-30"}
        ).json()["groups"]
        == 0
    )


def test_explanation_reports_winning_rule_per_field_and_manual_override(app_context):
    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    first, second = events(client)
    project = create_project(client)
    attribute(
        client, [first["id"]], purpose="study", project_id=project["id"], remember_scope="app"
    )
    attribute(client, [second["id"]], purpose="work")
    explanation = client.get(f"/api/events/{second['id']}/context/explanation").json()
    assert explanation["fields"]["purpose"]["origin"] == "manual"
    assert explanation["fields"]["project_id"]["rule_id"] == explanation["matched_rules"][0]["id"]
    assert explanation["matched_rules"][0]["effective_fields"] == ["project_id"]
    assert explanation["context"] == events(client)[1]["context"]
    assert client.get("/api/events/missing/context/explanation").status_code == 404


def test_undo_failure_rolls_back_decisions_audit_and_statistics(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    saved = attribute(client, [events(client)[0]["id"]], purpose="work")
    before = events(client)

    def fail(*args, **kwargs):
        raise RuntimeError("Undo processing failed")

    monkeypatch.setattr(SQLiteRepository, "replace_daily", fail)
    with pytest.raises(RuntimeError, match="Undo processing failed"):
        client.post(f"/api/activity-context/changes/{saved['change_id']}/undo")
    assert events(client) == before
    with app.state.sessions() as db:
        assert db.get(ContextChangeRow, saved["change_id"]).undone_at is None


def test_project_goal_uses_lifetime_active_time_independent_of_selected_range(app_context):
    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    project = create_project(client, goal_seconds=180)
    attribute(client, [e["id"] for e in events(client)], project_id=project["id"])
    item = client.get("/api/projects", params={"start": "2026-10-01", "end": "2026-10-31"}).json()[
        "items"
    ][0]
    assert item["active_seconds"] == 0
    assert item["lifetime_active_seconds"] == 120
    assert item["goal_progress"] == {
        "active_seconds": 120,
        "remaining_seconds": 60,
        "ratio": 2 / 3,
        "reached": False,
    }
    client.put(f"/api/projects/{project['id']}", json={"name": "改名仍保留目标"}).raise_for_status()
    assert client.get("/api/projects", params=RANGE).json()["items"][0]["goal_seconds"] == 180
    client.put(
        f"/api/projects/{project['id']}",
        json={"name": project["name"], "goal_seconds": 60, "archived": True},
    ).raise_for_status()
    item = client.get("/api/projects", params=RANGE).json()["items"][0]
    assert item["goal_progress"]["ratio"] == 2
    assert item["goal_progress"]["remaining_seconds"] == 0
    for value in [0, -1, 360_000_001, "NaN"]:
        assert (
            client.post("/api/projects", json={"name": "目标", "goal_seconds": value}).status_code
            == 422
        )
    client.put(
        f"/api/projects/{project['id']}", json={"name": project["name"], "goal_seconds": None}
    ).raise_for_status()
    assert client.get("/api/projects", params=RANGE).json()["items"][0]["goal_progress"] is None


def test_goal_and_history_migration_roundtrip_preserves_original_data(app_context):
    client, app, _, _, migration = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    original = raw_facts(app)
    project = create_project(client, goal_seconds=3600)
    attribute(client, [events(client)[0]["id"]], project_id=project["id"])
    command.check(migration)
    command.downgrade(migration, "0012")
    command.upgrade(migration, "head")
    client.post("/api/reprocess").raise_for_status()
    assert events(client)[0]["context"]["project_id"] == project["id"]
    assert client.get("/api/projects", params=RANGE).json()["items"][0]["goal_seconds"] is None
    assert client.get("/api/activity-context/changes").json()["items"] == []
    assert raw_facts(app) == original


@pytest.mark.parametrize(
    "endpoint", ["/api/activity-context/pending", "/api/activity-context/pending/events"]
)
def test_pending_range_validation(app_context, endpoint):
    client, _, _, _, _ = app_context
    params = {**RANGE, "source": "aw", "app": "code.exe"}
    for values in [{"end": "2026-09-28"}, {"limit": 0}, {"limit": 1001}, {"end": "9999-12-31"}]:
        assert client.get(endpoint, params={**params, **values}).status_code == 422
