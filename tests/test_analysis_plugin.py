"""Real extension lifecycle, bounded assets and atomic manual changes on synthetic data."""

import json
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from leisurelog.adapters.plugin_pages import PluginPageHost, PluginResources
from leisurelog.analysis_integration import ANALYSIS_ID, ANALYSIS_PERMISSIONS
from leisurelog.api.plugin_features import install_feature_routes
from leisurelog.domain.plugin_extensions import (
    AnalysisRejected,
    AnalysisRequest,
    AnalysisResult,
    AnalyticsContribution,
    ExtensionEndpoint,
    ExtensionPageRoute,
    GameTypeChange,
    HostExtensionBindings,
    JsonSnapshot,
    PageContribution,
)
from leisurelog.domain.plugin_runtime import PluginContributions
from leisurelog.domain.plugins import PluginCapability as Capability
from leisurelog.domain.plugins import PluginPermission as Permission
from leisurelog.game_integration import PLAYNITE_ID, PLAYNITE_PERMISSIONS
from leisurelog.plugin_api import Classification
from leisurelog.repositories.models import GameTypeOverrideRow
from leisurelog.services.plugin_runtime import PluginOperationError
from leisurelog_plugins.game_analysis import GameAnalysis
from tests.test_game_preferences import save
from tests.test_game_statistics import detail, install, listing
from tests.test_games import game
from tests.test_pipeline import WINDOW
from tests.test_plugin_runtime import activity, definition, eventually, status

pytest_plugins = ["tests.test_pipeline", "tests.test_plugin_api", "tests.test_plugin_runtime"]


def enable(client, grants=ANALYSIS_PERMISSIONS):
    return client.post(
        "/api/plugins/" + ANALYSIS_ID + "/enable",
        json={
            "grants": {ANALYSIS_ID: [value.value for value in grants]},
        },
    )


def test_analysis_disable_keeps_source_manual_choices_and_core_collection(app_context):
    client, app, payloads, _, _ = app_context
    row = game()
    install(app, row)
    key = "playnite:" + row["id"]
    save(client, key, "rpg").raise_for_status()
    before = detail(client, key)["item"]["game_type"]
    client.post("/api/plugins/" + ANALYSIS_ID + "/disable", json={}).raise_for_status()
    assert status(app.state.plugins, PLAYNITE_ID)["state"] == "running"
    assert client.get("/api/game-statistics").status_code == 503
    assert client.get("/games").status_code == 503
    assert "仍然保留" in client.get("/games").text
    assert client.get("/api/plugin-navigation").json()["pages"] == []
    for payload in payloads:
        payload["data"]["app"] = "YuanShen.exe"
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    assert {e["classification"]["category"] for e in client.get("/api/events").json()} == {"game"}
    enable(client).raise_for_status()
    assert detail(client, key)["item"]["game_type"] == before
    assert len(client.get("/api/plugin-navigation").json()["pages"]) == 2


def test_saved_library_is_readable_without_running_playnite(app_context):
    client, app, _, _, _ = app_context
    install(app, game())
    app.state.plugins.disable(PLAYNITE_ID)
    assert listing(client, scope="all")["total"] == 1
    assert client.get("/game-preferences").status_code == 200
    assert status(app.state.plugins, ANALYSIS_ID)["state"] == "running"


def test_read_permissions_do_not_grant_details_or_manual_writes(app_context):
    client, app, _, _, _ = app_context
    row = game()
    install(app, row)
    app.state.plugins.disable(ANALYSIS_ID)
    enable(client, (Permission.SUMMARY_READ, Permission.GAME_STATISTICS_READ)).raise_for_status()
    assert listing(client, scope="all")["total"] == 1
    key = "playnite:" + row["id"]
    assert client.get("/api/game-statistics/" + key).status_code == 503
    assert save(client, key).status_code == 503
    assert client.get("/api/game-preferences?start=2026-01-01&end=2026-12-31").status_code == 200
    with app.state.sessions() as db:
        assert db.get(GameTypeOverrideRow, key) is None
    assert status(app.state.plugins, ANALYSIS_ID)["state"] == "running"


@pytest.mark.parametrize("failure", ["exception", "invalid", "timeout"])
def test_analysis_failure_withdraws_pages_and_core_sync_recovers(app_context, monkeypatch, failure):
    client, app, payloads, _, _ = app_context
    original, release = GameAnalysis.run, Event()
    app.state.plugins.extensions._timeout = 0.08

    def fail(self, request):
        if self.view != "listing":
            return original(self, request)
        if failure == "exception":
            raise RuntimeError("private title must not appear in plugin state")
        if failure == "invalid":
            return {"repository": object()}
        release.wait(3)
        return original(self, request)

    monkeypatch.setattr(GameAnalysis, "run", fail)
    try:
        assert client.get("/api/game-statistics").status_code == 503
        state = status(app.state.plugins, ANALYSIS_ID)
        assert state["state"] == "failed"
        assert "private title" not in json.dumps(state)
        assert client.get("/api/plugin-navigation").json()["pages"] == []
        assert status(app.state.plugins, PLAYNITE_ID)["state"] == "running"
        client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
        payloads[1]["duration"] = 80
        assert client.post("/api/sync/activitywatch", json=WINDOW).json()["changed"] == 1
        if failure == "timeout":
            assert enable(client).status_code == 409
    finally:
        release.set()
    eventually(lambda: not app.state.plugins._workers.busy(ANALYSIS_ID))
    monkeypatch.setattr(GameAnalysis, "run", original)
    app.state.plugins.extensions._timeout = 2
    enable(client).raise_for_status()
    assert client.get("/api/game-statistics").status_code == 200


def test_projection_has_no_live_objects_raw_payload_url_or_installation_path(
    app_context, monkeypatch
):
    client, app, _, _, _ = app_context
    row = game()
    row["directory"] = r"D:\PrivateInstall\NeverExpose"
    install(app, row)
    original, captured = GameAnalysis.run, []

    def inspect(self, request):
        captured.append(request)
        return original(self, request)

    monkeypatch.setattr(GameAnalysis, "run", inspect)
    listing(client, scope="all")
    value = captured[-1]
    assert type(value) is AnalysisRequest
    assert type(value.data) is JsonSnapshot
    assert "PrivateInstall" not in value.data.json
    assert not {"raw_data", "payload", "url", "directory"} & set(value.data.value()["items"][0])
    copy = value.data.value()
    copy["items"][0]["name"] = "Changed outside host"
    assert listing(client, scope="all")["items"][0]["name"] == row["name"]
    assert value.data.value()["items"][0]["name"] == row["name"]


def test_revocation_during_manual_response_rolls_back_write(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    row = game()
    install(app, row)
    key = "playnite:" + row["id"]
    save(client, key, "rpg").raise_for_status()
    original, entered, release, responses = GameAnalysis.run, Event(), Event(), []

    def wait(self, request):
        if (
            self.view == "detail"
            and request.parameters.value().get("body", {}).get("primary") == "card"
        ):
            entered.set()
            release.wait(2)
        return original(self, request)

    monkeypatch.setattr(GameAnalysis, "run", wait)
    request_thread = Thread(target=lambda: responses.append(save(client, key, "card")))
    request_thread.start()
    assert entered.wait(1)
    revoke_thread = Thread(
        target=lambda: app.state.plugins.revoke(
            ANALYSIS_ID,
            Permission.GAME_TYPES_WRITE,
        )
    )
    revoke_thread.start()
    try:
        eventually(lambda: status(app.state.plugins, ANALYSIS_ID)["state"] != "running")
    finally:
        release.set()
    request_thread.join(3)
    revoke_thread.join(3)
    assert not request_thread.is_alive() and not revoke_thread.is_alive()
    assert responses[0].status_code == 503
    with app.state.sessions() as db:
        assert db.get(GameTypeOverrideRow, key).primary_type == "rpg"
    assert status(app.state.plugins, PLAYNITE_ID)["state"] == "running"


def test_old_generation_cannot_commit_after_reenable(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    row = game()
    install(app, row)
    key = "playnite:" + row["id"]
    save(client, key, "rpg").raise_for_status()
    extensions, runtime = app.state.plugins.extensions, app.state.plugins
    original = extensions.commit

    def change_generation(ticket, commit):
        runtime.disable(ANALYSIS_ID)
        runtime.enable(ANALYSIS_ID, {ANALYSIS_ID: ANALYSIS_PERMISSIONS})
        original(ticket, commit)

    monkeypatch.setattr(extensions, "commit", change_generation)
    assert save(client, key, "card").status_code == 503
    assert status(runtime, ANALYSIS_ID)["state"] == "running"
    with app.state.sessions() as db:
        assert db.get(GameTypeOverrideRow, key).primary_type == "rpg"


def test_read_endpoint_cannot_apply_a_write_proposal(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    row = game()
    install(app, row)
    key = "playnite:" + row["id"]
    monkeypatch.setattr(
        GameAnalysis,
        "run",
        lambda self, request: AnalysisResult(
            change=GameTypeChange(key, "card"),
        ),
    )
    assert client.get("/api/game-statistics").status_code == 503
    with app.state.sessions() as db:
        assert db.get(GameTypeOverrideRow, key) is None
    assert status(app.state.plugins, ANALYSIS_ID)["state"] == "failed"


def test_expected_input_errors_keep_plugin_and_navigation_running(app_context, monkeypatch):
    client, app, _, _, _ = app_context

    def reject(self, request):
        raise AnalysisRejected("合成输入不适用", 422)

    monkeypatch.setattr(GameAnalysis, "run", reject)
    assert client.get("/api/game-types").status_code == 422
    assert status(app.state.plugins, ANALYSIS_ID)["state"] == "running"
    assert len(client.get("/api/plugin-navigation").json()["pages"]) == 2
    assert client.get("/api/game-statistics?limit=1&limit=2").status_code == 422
    assert client.put("/api/game-types/key", content=b"x" * 16385).status_code == 413


@pytest.mark.parametrize("enabled", [{}, {PLAYNITE_ID: [p.value for p in PLAYNITE_PERMISSIONS]}])
def test_existing_saved_selection_is_not_silently_granted_new_analysis(application, enabled):
    path = application.settings.plugin_state_path
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps({"version": 1, "revision": 4, "enabled": enabled})
    path.write_text(content, encoding="utf-8")
    with TestClient(application(None)) as client:
        assert client.get("/api/game-statistics").status_code == 503
        assert client.get("/health").status_code == 200
        assert client.post("/api/sync/activitywatch", json=WINDOW).status_code == 200
        assert path.read_text(encoding="utf-8") == content
        enable(client).raise_for_status()
        assert client.get("/api/game-statistics").status_code == 200


def test_official_pages_own_assets_and_cannot_escape_their_resource_root(app_context):
    client, app, _, _, _ = app_context
    for page in ("/games", "/game-preferences"):
        response = client.get(page)
        assert response.status_code == 200
        assert "/plugin-assets/leisurelog.game-analysis/" in response.text
        assert "data-plugin-navigation" in response.text
    asset = "/plugin-assets/" + ANALYSIS_ID + "/game-statistics.js"
    assert client.get(asset).status_code == 200
    for name in ("not-listed.js", "..%2Fgame_analysis%2F__init__.py", "game-statistics.js%5C.."):
        assert client.get("/plugin-assets/" + ANALYSIS_ID + "/" + name).status_code == 404
    assert client.get("/static/game-statistics.js").status_code == 404
    app.state.plugins.disable(ANALYSIS_ID)
    assert client.get(asset).status_code == 503


@pytest.mark.parametrize("path", ["/", "/api/events", "/static/feature.js"])
def test_host_rejects_url_claims_over_core_routes(path):
    from leisurelog.main import create_app

    with pytest.raises(ValueError, match="冲突"):
        install_feature_routes(
            create_app(), (), (ExtensionPageRoute("example.test", "page", path),)
        )


def test_duplicate_and_prefixed_hidden_router_claims_are_rejected():
    app, router = FastAPI(), APIRouter()
    router.add_api_route("/hidden", lambda: {}, include_in_schema=False)
    app.include_router(router, prefix="/prefix")
    with pytest.raises(ValueError, match="冲突"):
        install_feature_routes(
            app, (), (ExtensionPageRoute("example.test", "page", "/prefix/hidden"),)
        )
    page = ExtensionPageRoute("example.test", "page", "/feature")
    with pytest.raises(ValueError, match="冲突"):
        install_feature_routes(FastAPI(), (), (page, page))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: object.__setattr__(p, "document", "../private.html"),
        lambda p: object.__setattr__(p, "assets", ("../private.html",)),
    ],
)
def test_forged_page_descriptors_fail_in_owned_factory(host, mutation):
    page = PageContribution("page", "Example", "page.html", ("page.html",))
    mutation(page)
    plugin = definition(
        caps=(Capability.PAGE,),
        create=lambda context: PluginContributions(
            pages=(page,),
        ),
    )
    runtime, _ = host([plugin])
    with pytest.raises(PluginOperationError):
        runtime.enable("example.test")
    assert runtime.extensions.pages() == []


@pytest.mark.parametrize("payload", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', "[]"])
def test_noncanonical_snapshots_are_rejected(payload):
    with pytest.raises(ValueError):
        JsonSnapshot(payload)


def test_analysis_ticket_and_scoped_pages_are_generic_not_game_specific(host, tmp_path):
    analyzer = SimpleNamespace(
        run=lambda request: AnalysisResult(
            JsonSnapshot.from_value(
                {
                    "observed": request.data.value(),
                }
            )
        )
    )
    plugin = definition(
        caps=(Capability.ANALYTICS, Capability.PAGE),
        permissions=(Permission.SUMMARY_READ,),
        create=lambda context: PluginContributions(
            analytics=(AnalyticsContribution("inspect", analyzer),),
            pages=(PageContribution("page", "Example", "page.html", ("page.html",)),),
        ),
    )
    runtime, _ = host([plugin])
    runtime.enable("example.test", {"example.test": (Permission.SUMMARY_READ,)})
    ticket = runtime.extensions.begin("example.test", "inspect")
    result = runtime.extensions.invoke(
        ticket,
        "inspect",
        AnalysisRequest(
            JsonSnapshot(),
            JsonSnapshot.from_value({"count": 3}),
        ),
    )
    assert result.data.value() == {"observed": {"count": 3}}
    (tmp_path / "page.html").write_text("<h1>Example</h1>", encoding="utf-8")
    page_host = PluginPageHost(runtime.extensions, {"example.test": tmp_path})
    assert page_host.navigation()["pages"][0]["url"] == "/plugins/example.test/pages/page"
    assert page_host.read("example.test", name="page")[0] == b"<h1>Example</h1>"
    runtime.disable("example.test")
    with pytest.raises(PluginOperationError):
        runtime.extensions.invoke(ticket, "inspect", AnalysisRequest(JsonSnapshot()))
    assert page_host.navigation()["pages"] == []


def test_openapi_describes_validated_plugin_query_and_body(app_context):
    client, _, _, _, _ = app_context
    paths = client.get("/openapi.json").json()["paths"]
    parameters = paths["/api/game-preferences"]["get"]["parameters"]
    assert {p["name"] for p in parameters if p["required"]} == {"start", "end"}
    assert paths["/api/game-types/{key}"]["put"]["requestBody"]["required"]
    assert all(not p["name"].startswith("request") for p in parameters)


@pytest.mark.parametrize("module", ["main", "services.processing", "api.routes"])
def test_game_projection_cannot_be_imported_outside_host_or_storage(module, tmp_path):
    from tests.test_architecture import scan

    findings = scan(
        tmp_path,
        {
            "leisurelog/"
            + module.replace(".", "/")
            + ".py": "from leisurelog.repositories.game_views import SQLiteGameViews",
        },
    )
    assert any(finding.rule == "feature-coupling" for finding in findings)


def test_architecture_has_no_legacy_feature_exceptions():
    from scripts.check_architecture import LEGACY_FEATURE_EDGES

    assert not LEGACY_FEATURE_EDGES


@pytest.mark.parametrize("bad_asset", ["missing", "oversized"])
def test_bad_page_resources_fail_without_affecting_other_plugins(host, tmp_path, bad_asset):
    if bad_asset == "oversized":
        (tmp_path / "page.html").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    plugin = definition(
        caps=(Capability.PAGE,),
        create=lambda context: PluginContributions(
            pages=(PageContribution("page", "Example", "page.html", ("page.html",)),),
        ),
    )
    unrelated = definition("example.unrelated")
    runtime, _ = host(
        [plugin, unrelated],
        page_validator=PluginResources(
            {
                "example.test": tmp_path,
            }
        ).validate,
    )
    runtime.enable("example.unrelated")
    with pytest.raises(PluginOperationError):
        runtime.enable("example.test")
    assert status(runtime, "example.unrelated")["state"] == "running"
    assert runtime.extensions.pages() == []


def test_analysis_work_does_not_displace_same_plugin_classifier(host):
    entered, release, results = Event(), Event(), []

    def analyze(request):
        entered.set()
        release.wait(1)
        return AnalysisResult()

    grants = (Permission.SUMMARY_READ, Permission.DETAILS_READ, Permission.CLASSIFICATION_PROPOSE)
    plugin = definition(
        caps=(Capability.ANALYTICS, Capability.CLASSIFIER),
        permissions=grants,
        create=lambda context: PluginContributions(
            classifiers=(
                SimpleNamespace(classify=lambda event: Classification("work", "Synthetic")),
            ),
            analytics=(AnalyticsContribution("slow", SimpleNamespace(run=analyze)),),
        ),
    )
    runtime, _ = host([plugin])
    runtime.enable("example.test", {"example.test": grants})
    ticket = runtime.extensions.begin("example.test", "slow")
    thread = Thread(
        target=lambda: results.append(
            runtime.extensions.invoke(
                ticket,
                "slow",
                AnalysisRequest(JsonSnapshot()),
            )
        )
    )
    thread.start()
    try:
        assert entered.wait(1)
        assert runtime.classify(activity()).content == "Synthetic"
    finally:
        release.set()
    thread.join(2)
    assert not thread.is_alive() and type(results[0]) is AnalysisResult
    assert status(runtime)["state"] == "running"


def test_host_projection_permission_cannot_be_bypassed_by_contribution(application, monkeypatch):
    from leisurelog.repositories.game_views import SQLiteGameViews

    observed = []
    monkeypatch.setattr(SQLiteGameViews, "read", lambda *args: observed.append("read"))
    plugin = definition(
        ANALYSIS_ID,
        caps=(Capability.ANALYTICS,),
        permissions=(Permission.SUMMARY_READ,),
        create=lambda context: PluginContributions(
            analytics=(
                AnalyticsContribution(
                    "detail", SimpleNamespace(run=lambda request: AnalysisResult())
                ),
            )
        ),
    )
    with TestClient(application((plugin,))) as client:
        enable(client, (Permission.SUMMARY_READ,)).raise_for_status()
        assert client.get("/api/game-statistics/private-key").status_code == 503
        assert observed == []
        assert client.get("/health").status_code == 200


def test_manual_change_and_disabled_choice_survive_restart(app_context):
    from leisurelog.main import create_app

    client, app, _, _, _ = app_context
    row = game()
    install(app, row)
    key = "playnite:" + row["id"]
    save(client, key, "rts").raise_for_status()
    app.state.plugins.disable(ANALYSIS_ID)
    with TestClient(create_app(app.state.settings, source=app.state.source)) as restarted:
        assert restarted.get("/games").status_code == 503
        assert restarted.get("/api/plugin-navigation").json()["pages"] == []
        enable(restarted).raise_for_status()
        assert detail(restarted, key)["item"]["game_type"]["primary"] == "rts"


def test_reviewed_custom_extension_uses_same_app_without_editing_main(application, tmp_path):
    from leisurelog.adapters.game_queries import EmptyQuery
    from leisurelog.main import create_app

    owner = "example.report"
    (tmp_path / "report.html").write_text("<h1>Isolated report</h1>", encoding="utf-8")
    plugin = definition(
        owner,
        caps=(Capability.ANALYTICS, Capability.PAGE),
        permissions=(Permission.SUMMARY_READ,),
        create=lambda context: PluginContributions(
            analytics=(
                AnalyticsContribution(
                    "inspect", SimpleNamespace(run=lambda request: AnalysisResult(request.data))
                ),
            ),
            pages=(
                PageContribution("report", "Synthetic report", "report.html", ("report.html",)),
            ),
        ),
    )

    class Host:
        def __init__(self, sessions, runtime):
            self.extensions = runtime.extensions

        def execute(self, endpoint, parameters):
            ticket = self.extensions.begin(
                owner, endpoint.name, permissions=(Permission.SUMMARY_READ,)
            )
            return self.extensions.invoke(
                ticket,
                endpoint.name,
                AnalysisRequest(
                    JsonSnapshot.from_value(parameters),
                    JsonSnapshot.from_value({"count": 3}),
                ),
            ).data.value()

    bindings = HostExtensionBindings(
        endpoints=(
            ExtensionEndpoint(
                owner, "inspect", "GET", "/api/plugin-analysis/example.report/inspect", EmptyQuery
            ),
        ),
        resources={owner: tmp_path},
        hosts={owner: Host},
    )
    app = create_app(
        application.settings,
        SimpleNamespace(fetch=lambda *args: []),
        plugins=(plugin,),
        extensions=bindings,
    )
    with TestClient(app) as client:
        client.post(
            "/api/plugins/" + owner + "/enable",
            json={
                "grants": {owner: [Permission.SUMMARY_READ.value]},
            },
        ).raise_for_status()
        assert client.get(bindings.endpoints[0].path).json() == {"count": 3}
        assert client.get("/plugins/" + owner + "/pages/report").text == "<h1>Isolated report</h1>"
        assert client.get("/api/plugin-navigation").json()["pages"][0]["plugin_id"] == owner
        assert client.get("/health").status_code == 200
