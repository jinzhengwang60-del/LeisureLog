"""Restore a ZIP into a different data directory, including saved plugin intent."""

import hashlib
import json
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from leisurelog.analysis_integration import ANALYSIS_ID, official_defaults
from leisurelog.config import Settings
from leisurelog.domain.plugins import PluginPermission as Permission
from leisurelog.main import create_app
from leisurelog.repositories.plugin_state import FilePluginState
from tests.test_analysis_plugin import enable
from tests.test_pipeline import WINDOW

pytest_plugins = ["tests.test_pipeline"]


@pytest.mark.parametrize("mode", ["defaults", "readonly", "disabled"])
def test_archive_restores_original_plugin_choices_and_current_records(app_context, tmp_path, mode):
    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    if mode != "defaults":
        app.state.plugins.disable(ANALYSIS_ID)
    if mode == "readonly":
        enable(
            client, (Permission.SUMMARY_READ, Permission.GAME_STATISTICS_READ)
        ).raise_for_status()
    state_path = app.state.storage.store.database.parent / "plugin-state.json"
    expected = next(
        p for p in client.get("/api/plugins").json()["plugins"] if p["id"] == ANALYSIS_ID
    )
    backup = client.post("/api/storage/backups")
    assert backup.status_code == 201, backup.text
    contents = client.get(backup.json()["archive_url"]).content
    recovered_dir = tmp_path / ("recovered-" + mode)
    recovered_dir.mkdir()
    with ZipFile(BytesIO(contents)) as archive:
        stored = archive.read("config/plugin-state.json")
        proof = json.loads(archive.read("verification.json"))["supplemental_files"]
        assert proof["config/plugin-state.json"] == {
            "bytes": len(stored),
            "sha256": hashlib.sha256(stored).hexdigest(),
        }
        if mode == "defaults":
            assert not state_path.exists()
            assert ANALYSIS_ID in json.loads(stored)["enabled"]
        else:
            assert stored == state_path.read_bytes()
        for filename, member in [
            ("activity.db", "leisurelog.db"),
            ("rules.yaml", "config/rules.yaml"),
            ("plugin-state.json", "config/plugin-state.json"),
        ]:
            (recovered_dir / filename).write_bytes(archive.read(member))
    settings = Settings(
        database_url="sqlite:///" + (recovered_dir / "activity.db").as_posix(),
        rules_path=recovered_dir / "rules.yaml",
        plugin_state_path=recovered_dir / "plugin-state.json",
        playnite_export_path=recovered_dir / "missing-export.json",
        playnite_bindings_path=recovered_dir / "missing-bindings.yaml",
        auto_sync_enabled=False,
        auto_backup_days=0,
    )
    with TestClient(create_app(settings)) as recovered:
        recovered.get("/health").raise_for_status()
        actual = next(
            p for p in recovered.get("/api/plugins").json()["plugins"] if p["id"] == ANALYSIS_ID
        )
        assert (actual["enabled"], actual["permissions"]) == (
            expected["enabled"],
            expected["permissions"],
        )
        assert recovered.get("/api/events").json() == client.get("/api/events").json()
        assert recovered.get("/api/sessions").json() == client.get("/api/sessions").json()


def test_snapshot_preserves_damaged_choices_and_does_not_change_defaults(tmp_path):
    state = tmp_path / "plugin-state.json"
    store = FilePluginState(state, defaults=official_defaults())
    assert json.loads(store.backup_snapshot())["enabled"]
    assert not state.exists()
    state.write_bytes(b"damaged configuration")
    assert store.backup_snapshot() == state.read_bytes()
    with pytest.raises(ValueError):
        store.load()
    state.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(ValueError):
        store.load()
    with pytest.raises(ValueError):
        store.backup_snapshot()


@pytest.mark.parametrize(
    "supplements",
    [
        {"../outside.json": b"bad"},
        {"config/rules.yaml": b"replace"},
        {"config/choice.json": b"x" * (1024 * 1024 + 1)},
    ],
)
def test_bad_config_snapshot_aborts_backup_and_cleans_partial_files(app_context, supplements):
    client, app, _, _, _ = app_context
    store = app.state.storage.store
    store._supplemental_files = lambda: supplements
    assert client.post("/api/storage/backups").status_code == 503
    assert list(store.directory.iterdir()) == []
    store._supplemental_files = lambda: {}
    assert client.post("/api/storage/backups").status_code == 201
