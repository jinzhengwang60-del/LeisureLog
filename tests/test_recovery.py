"""Exercise real full bundles, rejected inputs and a recovered application."""

import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

from leisurelog.config import Settings
from leisurelog.main import create_app
from leisurelog.recovery import main, recover_archive
from tests.test_pipeline import WINDOW

pytest_plugins = ["tests.test_pipeline"]


def full_backup(client, tmp_path):
    entry = client.post("/api/storage/backups")
    entry.raise_for_status()
    path = tmp_path / "complete.zip"
    path.write_bytes(client.get(entry.json()["archive_url"]).content)
    return path


def test_verified_recovery_preserves_corrections_and_restarts(app_context, tmp_path):
    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    key = client.get("/api/events").json()[0]["id"]
    client.put(f"/api/events/{key}/override", json={"category": "work"}).raise_for_status()
    before = client.get("/api/events").json()
    app.state.plugins.disable("leisurelog.playnite")
    archive = full_backup(client, tmp_path)
    target = tmp_path / "recovered"
    result = recover_archive(archive, target)
    assert result["database_revision"] == "0013" and result["plugin_state_restored"]
    settings = Settings(
        database_url="sqlite:///" + (target / "data/leisurelog.db").as_posix(),
        rules_path=target / "config/rules.yaml",
        auto_sync_enabled=False, auto_backup_days=0,
        playnite_export_path=tmp_path / "absent.json",
    )
    with TestClient(create_app(settings)) as recovered:
        assert recovered.get("/health").status_code == 200
        assert recovered.get("/api/events").json() == before
        recovered.post("/api/reprocess").raise_for_status()
        assert recovered.get("/api/events").json() == before
        states = recovered.get("/api/plugins").json()["plugins"]
        playnite = next(item for item in states if item["id"] == "leisurelog.playnite")
        assert playnite["enabled"] is False
    assert client.get("/api/events").json() == before
    assert archive.exists()
    with pytest.raises(FileExistsError):
        recover_archive(archive, target)


@pytest.mark.parametrize(
    "damage", ["database", "rules", "manifest", "supplement", "path", "missing"]
)
def test_invalid_bundles_do_not_leave_a_recovery_or_touch_original(app_context, tmp_path, damage):
    client, _, _, _, _ = app_context
    archive = full_backup(client, tmp_path)
    original = archive.read_bytes()
    with ZipFile(BytesIO(original)) as source:
        files = {name: source.read(name) for name in source.namelist()}
    if damage == "database":
        files["leisurelog.db"] = b"broken database"
    elif damage == "rules":
        files["config/rules.yaml"] += b"\n# changed after backup\n"
    elif damage == "manifest":
        files["verification.json"] = b"[]"
    elif damage == "supplement":
        files["config/plugin-state.json"] += b" "
    elif damage == "path":
        files["../outside.txt"] = b"invalid path"
    else:
        del files["leisurelog.db"]
    bad = tmp_path / "broken.zip"
    with ZipFile(bad, "w", compression=ZIP_DEFLATED) as output:
        for name, value in files.items():
            output.writestr(name, value)
    target = tmp_path / "must-not-exist"
    assert main([str(bad), "--destination", str(target)]) == 2
    assert not target.exists() and not (tmp_path / "outside.txt").exists()
    assert archive.read_bytes() == original
    assert list(tmp_path.glob(".leisurelog-recovery-*")) == []
    assert client.get("/health").status_code == 200


def test_legacy_full_backup_and_existing_destination(app_context, tmp_path):
    client, _, _, _, _ = app_context
    archive = full_backup(client, tmp_path)
    with ZipFile(archive) as source:
        files = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(files["verification.json"])
    del manifest["files"]
    del manifest["supplemental_files"]
    del files["config/plugin-state.json"]
    files["verification.json"] = json.dumps(manifest).encode()
    legacy = tmp_path / "legacy.zip"
    with ZipFile(legacy, "w") as output:
        for name, value in files.items():
            output.writestr(name, value)
    destination = tmp_path / "legacy-recovery"
    assert not recover_archive(legacy, destination)["plugin_state_restored"]
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    assert main([str(legacy), "--destination", str(destination)]) == 2
    assert marker.read_text(encoding="utf-8") == "keep"
