import sqlite3
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from leisurelog.config import Settings
from leisurelog.main import create_app
from leisurelog.repositories.storage import connect_readonly, fingerprint, verify_restore
from tests.test_pipeline import WINDOW

pytest_plugins = ["tests.test_pipeline"]


def test_snapshot_download_and_restored_app_preserve_data(app_context, tmp_path):
    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    event_id = client.get("/api/events").json()[0]["id"]
    client.put(
        "/api/events/overrides",
        json={
            "event_ids": [event_id],
            "category": "work",
            "content": "备份测试",
            "remember_scope": "app",
            "tags": ["保留"],
        },
    ).raise_for_status()
    before = client.get("/api/storage").json()
    assert before["counts"]["activity_events"] == 2
    assert before["counts"]["manual_overrides"] == 1
    assert before["counts"]["learned_rules"] == 1
    assert before["earliest_record_at"].endswith("+00:00")
    assert before["live_bytes"] >= before["database_bytes"] > 0
    first = client.post("/api/storage/backups")
    assert first.status_code == 201, first.text
    backup = first.json()
    assert backup["verified"] is True
    assert backup["counts"]["raw_events"] == 2
    second = client.post("/api/storage/backups").json()
    assert second["name"] != backup["name"]
    overview = client.get("/api/storage").json()
    assert len(overview["backups"]) == 2
    assert overview["backup_bytes"] >= backup["bytes"] + second["bytes"]
    response = client.get(backup["download_url"])
    assert response.status_code == 200
    assert len(response.content) == backup["bytes"]
    archive_response = client.get(backup["archive_url"])
    assert archive_response.status_code == 200
    with ZipFile(BytesIO(archive_response.content)) as archive:
        assert set(archive.namelist()) == {
            "leisurelog.db",
            "config/rules.yaml",
            "verification.json",
        }
        assert archive.read("leisurelog.db") == response.content
        assert archive.read("config/rules.yaml") == app.state.settings.rules_path.read_bytes()
    restored = tmp_path / "downloaded.db"
    restored.write_bytes(response.content)
    with connect_readonly(restored) as db:
        expected = fingerprint(db)
    with connect_readonly(app.state.storage.store.database) as db:
        assert fingerprint(db) == expected
    with TestClient(
        create_app(
            Settings(
                database_url="sqlite:///" + restored.as_posix(),
                rules_path=app.state.settings.rules_path,
                auto_sync_enabled=False,
            )
        )
    ) as recovered:
        assert recovered.get("/health").status_code == 200
        assert recovered.get("/api/events").json() == client.get("/api/events").json()
        assert recovered.get("/api/sessions").json() == client.get("/api/sessions").json()
        assert (
            recovered.get("/api/classification/rules").json()
            == client.get("/api/classification/rules").json()
        )
        recovered.post("/api/reprocess").raise_for_status()
        assert recovered.get("/api/events").json() == client.get("/api/events").json()
    assert (
        Path(overview["backup_directory"], backup["name"]).with_suffix(".rules.yaml").read_bytes()
        == app.state.settings.rules_path.read_bytes()
    )
    assert client.get("/api/storage/backups/missing.db/download").status_code == 404
    assert client.get("/api/storage/backups/%2E%2E%5Csecret.db/download").status_code == 404


def test_backup_failure_cleanup_and_busy(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    store = app.state.storage.store
    store.lock.acquire()
    try:
        assert client.post("/api/storage/backups").status_code == 409
    finally:
        store.lock.release()

    def fail(path):
        raise ValueError("simulated restore mismatch")

    with monkeypatch.context() as patch:
        patch.setattr("leisurelog.repositories.storage.verify_restore", fail)
        assert client.post("/api/storage/backups").status_code == 503
    assert list(store.directory.iterdir()) == []
    assert client.post("/api/storage/backups").status_code == 201


def test_backup_with_uncommitted_wal_write_and_empty_range(app_context):
    client, app, _, _, _ = app_context
    assert client.get("/api/storage").json()["earliest_record_at"] is None
    # Another writer's uncommitted changes must never leak into the snapshot.
    writer = sqlite3.connect(app.state.storage.store.database)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "INSERT INTO learned_rules VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "uncommitted",
                "aw",
                "app",
                "app",
                "app",
                '{"category":"game","origin":"learned","tags":[]}',
                "2026-09-30",
            ),
        )
        result = client.post("/api/storage/backups")
        assert result.status_code == 201
        assert result.json()["counts"]["learned_rules"] == 0
    finally:
        writer.rollback()
        writer.close()


def test_restore_verification_rejects_corruption(tmp_path):
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError):
        verify_restore(broken)
