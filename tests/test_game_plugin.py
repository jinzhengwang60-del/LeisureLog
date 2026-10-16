"""Actual catalog migration boundaries, lifecycle races and continued core collection."""

import json
from dataclasses import replace
from datetime import timedelta
from threading import Event, Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from leisurelog.adapters.catalog_files import LocalGameCatalogFiles
from leisurelog.domain.game_catalog import (
    GameCatalogFiles,
    GameCatalogImport,
    GameCatalogSnapshot,
    GameCatalogUnavailable,
    GameMatch,
)
from leisurelog.domain.models import Classification
from leisurelog.domain.plugin_runtime import PluginContributions
from leisurelog.domain.plugins import PluginCapability as Capability
from leisurelog.domain.plugins import PluginPermission as Permission
from leisurelog.game_integration import PLAYNITE_ID, PLAYNITE_PERMISSIONS, validate_playnite_import
from leisurelog.main import create_app
from leisurelog.repositories.games import SQLiteGameCatalog
from leisurelog.repositories.models import GameSnapshotRow, RawEventRow
from leisurelog.runtime import AutomaticSync
from leisurelog.services.plugin_access import PluginAccessDenied
from leisurelog.services.plugin_runtime import PluginOperationError
from leisurelog_plugins.playnite import CatalogClassifier, parse_export
from tests.test_games import catalog, game
from tests.test_pipeline import START, WINDOW, event
from tests.test_plugin_runtime import definition, status

pytest_plugins = ["tests.test_pipeline", "tests.test_plugin_runtime"]


def proposal(row=None):
    payload = catalog(row or game())
    return GameCatalogImport(json.dumps(payload), tuple(parse_export(payload)))


def write_catalog(app, *rows):
    app.state.settings.playnite_export_path.write_text(
        json.dumps(catalog(*rows), ensure_ascii=False), encoding="utf-8"
    )


def game_definition(create, *, caps=None, permissions=PLAYNITE_PERMISSIONS):
    return definition(
        PLAYNITE_ID,
        create=create,
        caps=caps or (Capability.GAME_CATALOG, Capability.CLASSIFIER),
        permissions=permissions,
    )


def activate(runtime):
    runtime.enable(PLAYNITE_ID, {PLAYNITE_ID: PLAYNITE_PERMISSIONS})


@pytest.mark.parametrize("mutation", [
    lambda p: replace(p, games=list(p.games)),
    lambda p: replace(p, games=(p.games[0], p.games[0])),
    lambda p: replace(p, games=(replace(p.games[0], installed=1),)),
    lambda p: replace(p, games=(replace(p.games[0], tags=["mutable"]),)),
    lambda p: replace(p, games=(replace(p.games[0], matches=(["game.exe", ""],)),)),
    lambda p: replace(p, raw_json=p.raw_json.replace('"schema_version": 1',
                                                  '"schema_version": true')),
    lambda p: replace(p, raw_json='{"schema_version":1,"schema_version":1,"games":[]}'),
    lambda p: replace(p, raw_json=json.dumps(catalog(game()))),
    lambda p: replace(p, raw_json=p.raw_json.replace('"schema_version": 1',
                                                  '"schema_version": 1, "invalid": NaN')),
])
def test_catalog_proposals_reject_mutability_ambiguity_and_source_mismatch(mutation):
    with pytest.raises((ValueError, TypeError)):
        validate_playnite_import(mutation(proposal()))


def test_unified_catalog_does_not_interpret_a_specific_source_schema():
    value = GameCatalogImport('{"custom_records":[]}', ())
    assert value.payload() == {"custom_records": []}
    with pytest.raises(GameCatalogUnavailable):
        validate_playnite_import(value)


def test_source_lifetime_playtime_stays_only_in_raw_snapshot():
    row = {**game(), "playtime": 999999999, "last_played": "2026-01-01"}
    value = proposal(row)
    assert value.payload()["games"][0]["playtime"] == 999999999
    assert not hasattr(value.games[0], "playtime")
    with pytest.raises(ValueError):
        GameMatch("manual")
    with pytest.raises(ValueError):
        GameCatalogFiles("x" * 10_000_001, "")


def test_fixed_file_reader_has_no_path_input_and_checks_byte_limit(tmp_path):
    export, bindings = tmp_path / "export.json", tmp_path / "bindings.yaml"
    reader = LocalGameCatalogFiles(export, bindings)
    with pytest.raises(GameCatalogUnavailable):
        reader.read()
    export.write_text("{}", encoding="utf-8-sig")
    bindings.write_text("bindings: []", encoding="utf-8")
    assert reader.read() == GameCatalogFiles("{}", "bindings: []")
    with pytest.raises(TypeError):
        reader.read(tmp_path / "elsewhere")
    bindings.write_bytes(b"x" * 1_000_001)
    with pytest.raises(GameCatalogUnavailable):
        reader.read()


def test_game_permissions_and_declared_contributions_are_required(host):
    plugin = game_definition(lambda context: PluginContributions())
    runtime, _ = host((plugin,))
    with pytest.raises(PluginOperationError) as error:
        runtime.enable(PLAYNITE_ID, {PLAYNITE_ID: [Permission.DETAILS_READ]})
    assert error.value.issue.code == "permission_required"
    assert status(runtime, PLAYNITE_ID)["state"] == "disabled"
    classifier_only = game_definition(
        lambda context: PluginContributions(game_catalog=SimpleNamespace(fetch=lambda: proposal())),
        caps=(Capability.CLASSIFIER,),
    )
    runtime2, _ = host((classifier_only,))
    with pytest.raises(PluginOperationError):
        activate(runtime2)
    assert not status(runtime2, PLAYNITE_ID)["enabled"]


def test_file_port_is_per_activation_and_old_reader_never_recovers(host):
    readers = []

    def create(context):
        readers.append(context.game_files)
        return PluginContributions(game_catalog=SimpleNamespace(fetch=lambda: proposal()))

    runtime, _ = host(
        (game_definition(create),),
        catalog_files={PLAYNITE_ID: SimpleNamespace(read=lambda: GameCatalogFiles("{}", ""))},
    )
    activate(runtime)
    assert readers[0].read().export_json == "{}"
    runtime.revoke(PLAYNITE_ID, Permission.FILE_IMPORT)
    with pytest.raises(PluginAccessDenied):
        readers[0].read()
    activate(runtime)
    assert readers[-1].read().export_json == "{}"
    with pytest.raises(PluginAccessDenied):
        readers[0].read()


def test_revocation_discards_inflight_files_and_blocks_late_import(host):
    entered, release = Event(), Event()
    host.releases.append(release)

    def read():
        entered.set()
        release.wait(1)
        return GameCatalogFiles("{}", "")

    contexts = []

    def create(context):
        contexts.append(context)
        return PluginContributions(game_catalog=SimpleNamespace(fetch=lambda: proposal()))

    runtime, _ = host(
        (game_definition(create),), catalog_files={PLAYNITE_ID: SimpleNamespace(read=read)}
    )
    activate(runtime)
    # No unmanaged plugin thread: the test drives the provider on a test-owned thread.
    from threading import Thread

    outcomes = []

    def invoke():
        try:
            contexts[0].game_files.read()
        except PluginAccessDenied:
            outcomes.append("revoked")

    thread = Thread(target=invoke)
    thread.start()
    assert entered.wait(1)
    runtime.disable(PLAYNITE_ID)
    release.set()
    thread.join(1)
    assert outcomes == ["revoked"]


def test_catalog_ticket_is_invalid_after_disable_and_new_activation(host):
    runtime, _ = host((game_definition(
        lambda context: PluginContributions(game_catalog=SimpleNamespace(fetch=lambda: proposal()))
    ),))
    activate(runtime)
    ticket = runtime.fetch_game_catalog(PLAYNITE_ID)
    runtime.disable(PLAYNITE_ID)
    activate(runtime)
    committed = []
    with pytest.raises(PluginOperationError) as error:
        runtime.commit_game_catalog(ticket, lambda: committed.append(True))
    assert error.value.issue.code == "catalog_stale"
    assert committed == []


def test_bounded_source_timeout_cannot_publish_late_result(host):
    release = Event()
    host.releases.append(release)
    value = proposal()

    def fetch():
        release.wait(1)
        return value

    runtime, workers = host((game_definition(
        lambda context: PluginContributions(game_catalog=SimpleNamespace(fetch=fetch))
    ),), catalog_timeout=0.03)
    activate(runtime)
    with pytest.raises(PluginOperationError):
        runtime.fetch_game_catalog(PLAYNITE_ID)
    assert status(runtime, PLAYNITE_ID)["state"] == "failed"
    assert workers.busy(PLAYNITE_ID)
    with pytest.raises(PluginOperationError):
        activate(runtime)
    release.set()


@pytest.mark.parametrize("kind", ["unknown", "uninstalled", "manual", "malformed-source"])
def test_invalid_catalog_and_game_match_faults_are_withdrawn(host, kind):
    row = game(installed=kind != "uninstalled")
    value = proposal(row)
    match = (
        GameMatch(str(uuid4())) if kind == "unknown"
        else Classification("work", origin="manual") if kind == "manual"
        else GameMatch(row["id"])
    )
    # An uninstalled ID is explicitly proposed from an eligible installed app's input.
    installed = value.games[0] if kind != "uninstalled" else replace(
        value.games[0], id=str(uuid4()), installed=True
    )
    snapshot = GameCatalogSnapshot("fixture", (value.games[0], installed)
                                   if kind == "uninstalled" else value.games)
    plugin = game_definition(lambda context: PluginContributions(
        game_catalog=SimpleNamespace(fetch=lambda: {"games": []}),
        game_classifier=SimpleNamespace(classify=lambda event, catalog: match),
    ))
    runtime, _ = host((plugin,), catalog_reader=SimpleNamespace(read=lambda: snapshot))
    activate(runtime)
    if kind == "malformed-source":
        with pytest.raises(PluginOperationError):
            runtime.fetch_game_catalog(PLAYNITE_ID)
    else:
        assert runtime.classify(event("test", 0, 60, "YuanShen.exe")) is None
    assert status(runtime, PLAYNITE_ID)["state"] == "failed"


def test_batch_reads_catalog_once_and_skips_unrelated_apps(host):
    value, reads, calls = proposal(), [], []
    classifier = CatalogClassifier()

    def classify(activity, catalog):
        calls.append(activity.app)
        return classifier.classify(activity, catalog)

    runtime, _ = host((game_definition(lambda context: PluginContributions(
        game_classifier=SimpleNamespace(classify=classify)
    )),), catalog_reader=SimpleNamespace(
        read=lambda: reads.append(True) or GameCatalogSnapshot(
            "fixture", value.games, namespace="playnite"
        )
    ))
    activate(runtime)
    batch = runtime.for_processing()
    for index in range(100):
        assert batch.classify(event(str(index), 0, 60, "not-a-game.exe")) is None
    result = batch.classify(event("game", 0, 60, "YUANSHEN.EXE"))
    assert result.origin == "playnite:" + value.games[0].id
    assert reads == [True] and calls == ["YUANSHEN.EXE"]
    runtime.disable(PLAYNITE_ID)
    assert batch.classify(event("old", 0, 60, "YuanShen.exe")) is None


@pytest.mark.parametrize("kind", ["media", "source"])
def test_metadata_read_cannot_displace_healthy_game_classification(host, kind):
    value, entered, release = proposal(), Event(), Event()
    host.releases.append(release)
    def read():
        entered.set()
        release.wait(1)
        return value

    runtime, _ = host((game_definition(lambda context: PluginContributions(
        game_catalog=SimpleNamespace(fetch=read), game_classifier=CatalogClassifier()
    )),), catalog_reader=SimpleNamespace(read=lambda: GameCatalogSnapshot(
        "fixture", value.games, namespace="playnite"
    )))
    activate(runtime)
    thread = Thread(target=(
        lambda: runtime.read_game_media(PLAYNITE_ID, read)
        if kind == "media" else runtime.fetch_game_catalog(PLAYNITE_ID)
    ))
    thread.start()
    try:
        assert entered.wait(1)
        result = runtime.classify(event("game", 0, 60, "YuanShen.exe"))
        assert result is not None and result.origin == "playnite:" + value.games[0].id
    finally:
        release.set()
        thread.join(1)


def test_missing_and_damaged_export_retains_catalog_and_recovers(app_context):
    client, app, payloads, _, _ = app_context
    row = {**game(), "playtime": 99999999}
    write_catalog(app, row)
    client.post("/api/games/playnite/import").raise_for_status()
    for payload in payloads:
        payload["data"]["app"] = "YuanShen.exe"
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    before = client.get("/api/sessions").json()
    app.state.settings.playnite_export_path.write_text("broken", encoding="utf-8")
    assert client.post("/api/games/playnite/import").status_code == 422
    state = status(app.state.plugins, PLAYNITE_ID)
    assert state["state"] == "running" and state["catalog_error"]["code"] == "catalog_unavailable"
    client.post("/api/reprocess").raise_for_status()
    assert client.get("/api/sessions").json() == before
    assert sum(s["active_seconds"] for s in before) == 120
    app.state.settings.playnite_export_path.unlink()
    assert client.post("/api/games/playnite/import").status_code == 422
    write_catalog(app, row)
    assert client.post("/api/games/playnite/import").json()["changed"] is False
    assert status(app.state.plugins, PLAYNITE_ID)["catalog_error"] is None
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(GameSnapshotRow)) == 1


def test_revoke_before_final_commit_rolls_back_catalog_and_derived_data(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    before = client.get("/api/sessions").json()
    write_catalog(app, game())
    original = app.state.plugins.commit_game_catalog

    def revoke(ticket, commit):
        app.state.plugins.revoke(PLAYNITE_ID, Permission.FILE_IMPORT)
        return original(ticket, commit)

    monkeypatch.setattr(app.state.plugins, "commit_game_catalog", revoke)
    assert client.post("/api/games/playnite/import").status_code == 409
    assert client.get("/api/games/playnite").json()["total"] == 0
    assert client.get("/api/sessions").json() == before
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(GameSnapshotRow)) == 0


def test_host_write_failure_rolls_back_and_later_retry_recovers(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    write_catalog(app, game())
    original = SQLiteGameCatalog.replace

    def failed(store, *args):
        original(store, *args)
        raise RuntimeError("synthetic persistence failure")

    with monkeypatch.context() as patch:
        patch.setattr(SQLiteGameCatalog, "replace", failed)
        with pytest.raises(RuntimeError):
            client.post("/api/games/playnite/import")
    assert client.get("/api/games/playnite").json()["total"] == 0
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    assert client.post("/api/games/playnite/import").json()["changed"] is True
    assert status(app.state.plugins, PLAYNITE_ID)["state"] == "running"


@pytest.mark.parametrize("failure", ["throw", "bad-result", "disabled", "damaged"])
def test_optional_catalog_failure_does_not_block_core_or_next_sync(app_context, failure):
    client, app, _, _, _ = app_context
    write_catalog(app, game())
    refresh = app.state.game_catalog.refresh
    if failure == "throw":
        def refresh():
            raise RuntimeError("synthetic metadata failure")
    elif failure == "bad-result":
        def refresh():
            return None
    elif failure == "disabled":
        app.state.plugins.disable(PLAYNITE_ID)
    else:
        app.state.settings.playnite_export_path.write_text("broken", encoding="utf-8")
    records = app.state.source.fetch(START, START + timedelta(hours=1), None)
    source = SimpleNamespace(fetch=lambda *args: records)
    sync = AutomaticSync(
        app.state.sessions, source, app.state.pipeline, app.state.settings, refresh
    )
    first = sync(Event())
    assert first["catalog"]["status"] == "unavailable"
    assert len(client.get("/api/events").json()) == 2
    assert len(client.get("/api/sessions").json()) == 1
    second = sync(Event())
    assert second["changed"] == 0
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RawEventRow)) == 2


def test_disabled_choice_is_saved_and_does_not_erase_history_on_restart(app_context):
    client, app, payloads, _, _ = app_context
    write_catalog(app, game())
    client.post("/api/games/playnite/import").raise_for_status()
    payloads[0]["data"]["app"] = "YuanShen.exe"
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    before = client.get("/api/sessions").json()
    app.state.plugins.disable(PLAYNITE_ID)
    assert client.get("/api/sessions").json() == before
    # The restarted host uses the saved empty intent rather than its compatibility default.
    with TestClient(create_app(app.state.settings, source=app.state.source)) as restarted:
        plugin = next(p for p in restarted.get("/api/plugins").json()["plugins"]
                      if p["id"] == PLAYNITE_ID)
        assert plugin["state"] == "disabled" and plugin["enabled"] is False
        assert restarted.get("/api/sessions").json() == before
        assert restarted.get("/api/games/playnite").json()["total"] == 1
        assert restarted.post("/api/games/playnite/import").status_code == 409
        restarted.post("/api/plugins/" + PLAYNITE_ID + "/enable", json={
            "grants": {PLAYNITE_ID: [p.value for p in PLAYNITE_PERMISSIONS]}
        }).raise_for_status()
        assert restarted.post("/api/games/playnite/import").json()["changed"] is False


def test_missing_official_package_does_not_stop_application(app_context, monkeypatch):
    from leisurelog import game_integration

    _, app, _, _, _ = app_context

    def missing(name):
        raise ImportError("synthetic missing official package")

    monkeypatch.setattr(game_integration, "import_module", missing)
    with TestClient(create_app(app.state.settings, source=app.state.source)) as client:
        assert client.get("/health").status_code == 200
        client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
        assert client.get("/api/library").status_code == 200
        assert client.get("/api/library/cover", params={"game": "missing"}).status_code == 404
        plugin = next(value for value in client.get("/api/plugins").json()["plugins"]
                      if value["id"] == PLAYNITE_ID)
        assert plugin["state"] == "failed"


@pytest.mark.parametrize("failure", ["source-exception", "source-timeout", "invalid-match"])
def test_real_game_worker_faults_preserve_core_sqlite_sync(
    app_context, tmp_path, monkeypatch, failure
):
    _, original_app, payloads, _, migration = app_context
    for payload in payloads:
        payload["data"]["app"] = "YuanShen.exe"
    records = original_app.state.source.fetch(START, START + timedelta(hours=1), None)
    source = SimpleNamespace(fetch=lambda *args: records)
    value, release = proposal(), Event()

    def fetch():
        if failure == "source-exception":
            raise RuntimeError("synthetic source failure")
        if failure == "source-timeout":
            release.wait(5)
        return value

    plugin = game_definition(lambda context: PluginContributions(
        game_catalog=SimpleNamespace(fetch=fetch),
        game_classifier=SimpleNamespace(
            classify=lambda event, catalog: GameMatch("99999999-0000-4000-8000-000000000000")
        ),
    ))
    url = "sqlite:///" + (tmp_path / "fault.db").as_posix()
    monkeypatch.setenv("LEISURELOG_DATABASE_URL", url)
    command.upgrade(migration, "head")
    settings = original_app.state.settings.model_copy(update={
        "database_url": url, "plugin_state_path": tmp_path / "fault-plugin-state.json"
    })
    app = create_app(settings, source, plugins=(plugin,))
    with TestClient(app) as client:
        activate(app.state.plugins)
        app.state.plugins._catalog_timeout = 0.03
        sync = AutomaticSync(
            app.state.sessions, source, app.state.pipeline, settings, app.state.game_catalog.refresh
        )
        try:
            sync(Event())
            assert status(app.state.plugins, PLAYNITE_ID)["state"] == "failed"
            assert client.get("/health").status_code == 200
            events = client.get("/api/events").json()
            assert len(events) == 2 and all(
                value["classification"]["category"] == "unknown" for value in events
            )
            assert sum(s["active_seconds"] for s in client.get("/api/sessions").json()) == 120
            assert sync(Event())["changed"] == 0
            with app.state.sessions() as db:
                assert db.scalar(select(func.count()).select_from(RawEventRow)) == 2
                assert db.scalar(select(func.count()).select_from(GameSnapshotRow)) == (
                    1 if failure == "invalid-match" else 0
                )
        finally:
            release.set()
