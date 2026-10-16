"""Management plans and HTTP controls on isolated state, real threads and SQLite."""

import json
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from leisurelog.domain.plugin_contracts import TaskBudget
from leisurelog.domain.plugin_runtime import PluginConfiguration, PluginContributions, ScheduledTask
from leisurelog.domain.plugins import PluginCapability as Capability
from leisurelog.domain.plugins import PluginDependency
from leisurelog.domain.plugins import PluginPermission as Permission
from leisurelog.repositories.models import RawEventRow
from leisurelog.repositories.plugin_state import FilePluginState
from tests.test_plugin_api import WINDOW
from tests.test_plugin_runtime import definition, eventually, status

pytest_plugins = ["tests.test_plugin_api", "tests.test_plugin_runtime", "tests.test_pipeline"]


def preview(client, owner, operation="enable", **parameters):
    return client.get(
        "/api/plugins/" + owner + "/plan",
        params={
            "operation": operation,
            **parameters,
        },
    )


def apply_enable(client, plan):
    return client.post(
        "/api/plugins/" + plan["plugin_id"] + "/enable",
        json={
            "expected_revision": plan["revision"],
            "grants": {target["id"]: target["default_grants"] for target in plan["targets"]},
        },
    )


def graph(calls):
    base = definition(
        "example.base",
        caps=(Capability.ANALYTICS,),
        permissions=(Permission.SUMMARY_READ, Permission.DETAILS_READ),
        create=lambda context: calls.append("base") or PluginContributions(),
    )
    dependent = definition(
        "example.dependent",
        dependencies=(PluginDependency("example.base", ">=0.1"),),
        create=lambda context: calls.append("dependent") or PluginContributions(),
    )
    unrelated = definition(
        "example.unrelated",
        create=lambda context: calls.append("unrelated") or PluginContributions(),
    )
    return base, dependent, unrelated


def test_management_page_is_available_with_no_plugins_and_preserves_core(application):
    with TestClient(application()) as client:
        response = client.get("/plugins")
        assert response.status_code == 200
        assert 'id="plugin-empty"' in response.text and 'href="/"' in response.text
        assert response.headers["cache-control"] == "no-store"
        for resource in ("plugins.js", "plugin-controls.js", "plugins.css"):
            assert client.get("/static/" + resource).status_code == 200
        assert client.get("/api/plugins").json()["plugins"] == []
        assert preview(client, "example.missing").status_code == 404
        client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
        assert len(client.get("/api/events").json()) == 1


def test_plans_do_not_run_factories_save_files_or_start_work(application):
    calls = []
    app = application(graph(calls))
    with TestClient(app) as client:
        before = client.get("/api/plugins").json()
        plan = preview(client, "example.dependent", expected_revision=0).json()
        assert [target["id"] for target in plan["targets"]] == ["example.base", "example.dependent"]
        assert plan["targets"][0]["required_permissions"] == ["activity.summary.read"]
        assert calls == []
        assert client.get("/api/plugins").json() == before
        assert not application.settings.plugin_state_path.exists()


def test_running_dependency_keeps_its_actual_grants_in_plan(application):
    calls = []
    app = application(graph(calls))
    with TestClient(app) as client:
        client.post(
            "/api/plugins/example.base/enable",
            json={
                "grants": {
                    "example.base": [Permission.SUMMARY_READ.value],
                }
            },
        ).raise_for_status()
        plan = preview(client, "example.dependent").json()
        assert plan["targets"][0]["already_running"]
        assert plan["targets"][0]["default_grants"] == [Permission.SUMMARY_READ.value]
        apply_enable(client, plan).raise_for_status()
        assert status(app.state.plugins, "example.base")["permissions"] == [
            Permission.SUMMARY_READ.value
        ]
        assert calls == ["base", "dependent"]


@pytest.mark.parametrize("operation", ["disable", "revoke"])
def test_stop_plan_and_action_affect_dependents_but_preserve_unrelated(application, operation):
    calls = []
    app = application(graph(calls))
    with TestClient(app) as client:
        apply_enable(client, preview(client, "example.dependent").json()).raise_for_status()
        apply_enable(client, preview(client, "example.unrelated").json()).raise_for_status()
        parameters = {"permission": Permission.SUMMARY_READ.value} if operation == "revoke" else {}
        plan = preview(client, "example.base", operation, **parameters).json()
        assert {target["id"] for target in plan["targets"]} == {"example.base", "example.dependent"}
        assert status(app.state.plugins, "example.base")["state"] == "running"
        if operation == "disable":
            response = client.post(
                "/api/plugins/example.base/disable",
                json={
                    "cascade": True,
                    "expected_revision": plan["revision"],
                },
            )
        else:
            response = client.delete(
                "/api/plugins/example.base/permissions/activity.summary.read",
                params={"expected_revision": plan["revision"]},
            )
        response.raise_for_status()
        assert status(app.state.plugins, "example.base")["state"] == "disabled"
        assert status(app.state.plugins, "example.dependent")["state"] == "disabled"
        assert status(app.state.plugins, "example.unrelated")["state"] == "running"
        assert len(calls) == 3


def test_stale_confirmation_cannot_apply_after_another_change(application):
    calls = []
    app = application(graph(calls))
    with TestClient(app) as client:
        plan = preview(client, "example.dependent").json()
        apply_enable(client, preview(client, "example.unrelated").json()).raise_for_status()
        response = apply_enable(client, plan)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "configuration_conflict"
        assert calls == ["unrelated"]
        assert preview(client, "example.dependent", expected_revision=0).status_code == 409


def test_saved_permission_subset_survives_failure_and_is_used_for_retry_preview(application):
    def fail(context):
        raise RuntimeError("private window title and path")

    plugin = definition(
        caps=(Capability.ANALYTICS,),
        permissions=(Permission.SUMMARY_READ, Permission.DETAILS_READ),
        create=fail,
    )
    path = application.settings.plugin_state_path
    FilePluginState(path).save(
        PluginConfiguration(1, {"example.test": (Permission.SUMMARY_READ,)}), expected_revision=0
    )
    with TestClient(application((plugin,))) as client:
        state = client.get("/api/plugins").json()
        assert state["plugins"][0]["state"] == "failed"
        assert state["plugins"][0]["permissions"] == []
        assert state["plugins"][0]["saved_permissions"] == [Permission.SUMMARY_READ.value]
        plan = preview(client, "example.test").json()
        assert plan["targets"][0]["default_grants"] == [Permission.SUMMARY_READ.value]
        assert "private window" not in json.dumps(state)
        assert preview(client, "example.test", "disable").status_code == 200


def test_required_host_grant_is_previewed_and_checked_before_factory(application):
    calls = []
    plugin = replace(
        definition(
            caps=(Capability.ANALYTICS,),
            permissions=(Permission.SUMMARY_READ, Permission.GAME_STATISTICS_READ),
            create=lambda context: calls.append("factory") or PluginContributions(),
        ),
        required_permissions=(Permission.GAME_STATISTICS_READ,),
    )
    with TestClient(application((plugin,))) as client:
        plan = preview(client, "example.test").json()
        assert set(plan["targets"][0]["required_permissions"]) == {
            Permission.SUMMARY_READ.value,
            Permission.GAME_STATISTICS_READ.value,
        }
        rejected = client.post(
            "/api/plugins/example.test/enable",
            json={
                "grants": {
                    "example.test": [Permission.SUMMARY_READ.value],
                }
            },
        )
        assert rejected.status_code == 409
        assert calls == []
        apply_enable(client, plan).raise_for_status()
        assert calls == ["factory"]


def test_missing_saved_selection_can_be_cleared_without_loading_code(application):
    path = application.settings.plugin_state_path
    FilePluginState(path).save(PluginConfiguration(1, {"example.removed": ()}), expected_revision=0)
    with TestClient(application()) as client:
        assert preview(client, "example.removed").status_code == 404
        plan = preview(client, "example.removed", "disable").json()
        assert plan["targets"][0]["id"] == "example.removed"
        client.post(
            "/api/plugins/example.removed/disable",
            json={
                "expected_revision": plan["revision"],
            },
        ).raise_for_status()
        assert client.get("/api/plugins").json()["plugins"] == []
        assert json.loads(path.read_text())["enabled"] == {}


def test_corrupt_settings_leave_page_and_core_usable_and_block_management(application):
    path = application.settings.plugin_state_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("broken", encoding="utf-8")
    with TestClient(application((definition(),))) as client:
        assert client.get("/plugins").status_code == 200
        assert (
            client.get("/api/plugins").json()["configuration_error"]["code"]
            == "configuration_invalid"
        )
        assert preview(client, "example.test").status_code == 409
        assert client.post("/api/sync/activitywatch", json=WINDOW).status_code == 200
        assert path.read_text() == "broken"


def test_stop_timeout_is_not_reported_as_a_running_or_fully_stopped_plugin(application):
    entered, release = Event(), Event()

    def run(context):
        entered.set()
        release.wait(5)

    plugin = definition(
        caps=(Capability.TASK,),
        create=lambda context: PluginContributions(
            tasks=(ScheduledTask("held", SimpleNamespace(run=run), budget=TaskBudget(10, 0.05)),),
        ),
    )
    app = application((plugin,))
    try:
        with TestClient(app) as client:
            apply_enable(client, preview(client, "example.test").json()).raise_for_status()
            assert entered.wait(1)
            plan = preview(client, "example.test", "disable").json()
            response = client.post(
                "/api/plugins/example.test/disable",
                json={
                    "expected_revision": plan["revision"],
                },
            )
            response.raise_for_status()
            item = response.json()["plugins"][0]
            assert item["state"] == "failed" and item["enabled"] is False
            assert item["last_error"]["code"] == "stop_timeout"
            assert any(work["running"] for work in item["workers"])
            assert preview(client, "example.test").status_code == 409
            assert client.get("/health").status_code == 200
            release.set()
            eventually(lambda: not app.state.plugins._workers.busy("example.test"))
            assert preview(client, "example.test").status_code == 200
    finally:
        release.set()


def test_readonly_selection_is_persisted_without_new_configuration_fields(application):
    plugin = definition(
        caps=(Capability.ANALYTICS,), permissions=(Permission.SUMMARY_READ, Permission.DETAILS_READ)
    )
    with TestClient(application((plugin,))) as client:
        plan = preview(client, "example.test").json()
        client.post(
            "/api/plugins/example.test/enable",
            json={
                "expected_revision": plan["revision"],
                "grants": {"example.test": [Permission.SUMMARY_READ.value]},
            },
        ).raise_for_status()
    saved = json.loads(application.settings.plugin_state_path.read_text())
    assert set(saved) == {"version", "revision", "enabled"}
    assert saved["version"] == 1
    with TestClient(application((plugin,))) as restarted:
        item = restarted.get("/api/plugins").json()["plugins"][0]
        assert item["state"] == "running"
        assert item["saved_permissions"] == item["permissions"] == [Permission.SUMMARY_READ.value]


def test_core_navigation_and_disabled_bookmarks_link_to_management(app_context):
    client, app, _, _, _ = app_context
    for path in (
        "/",
        "/review",
        "/unclassified",
        "/statistics",
        "/projects",
        "/library",
        "/games",
        "/game-preferences",
        "/plugins",
    ):
        assert 'href="/plugins"' in client.get(path).text
    app.state.plugins.disable("leisurelog.game-analysis")
    assert 'href="/plugins"' in client.get("/games").text
    assert client.get("/plugins").status_code == 200


def test_official_analysis_management_preserves_raw_data_and_manual_type(app_context):
    from tests.test_game_preferences import save
    from tests.test_game_statistics import detail, install
    from tests.test_games import game
    from tests.test_pipeline import WINDOW as ACTIVITY_WINDOW

    client, app, _, _, _ = app_context
    row = game()
    install(app, row)
    key = "playnite:" + row["id"]
    client.post("/api/sync/activitywatch", json=ACTIVITY_WINDOW).raise_for_status()
    save(client, key, "card").raise_for_status()
    with app.state.sessions() as db:
        raw = [r.payload for r in db.scalars(select(RawEventRow).order_by(RawEventRow.id))]
    plan = preview(client, "leisurelog.game-analysis", "disable").json()
    client.post(
        "/api/plugins/leisurelog.game-analysis/disable",
        json={
            "expected_revision": plan["revision"],
        },
    ).raise_for_status()
    assert client.get("/api/game-statistics").status_code == 503
    client.post("/api/sync/activitywatch", json=ACTIVITY_WINDOW).raise_for_status()
    apply_enable(client, preview(client, "leisurelog.game-analysis").json()).raise_for_status()
    assert detail(client, key)["item"]["game_type"]["primary"] == "card"
    with app.state.sessions() as db:
        assert [r.payload for r in db.scalars(select(RawEventRow).order_by(RawEventRow.id))] == raw
