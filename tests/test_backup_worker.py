"""Backups remain available when collection is disabled or the source is offline."""

from threading import Event

import pytest
from fastapi.testclient import TestClient

from leisurelog.adapters.scheduler import PeriodicSync
from leisurelog.main import create_app
from leisurelog.runtime import AutomaticSync
from leisurelog.services.storage import AutomaticBackup, StorageService

pytest_plugins = ["tests.test_pipeline"]


def test_offline_sync_does_not_prevent_a_verified_backup(app_context):
    _, app, _, _, _ = app_context

    class OfflineSource:
        def fetch(self, *args):
            raise ConnectionError("Simulated offline ActivityWatch")

    run = AutomaticSync(app.state.sessions, OfflineSource(), app.state.pipeline, app.state.settings)
    with pytest.raises(ConnectionError):
        run(Event())
    result = AutomaticBackup(app.state.storage, every_days=7, keep=4)(Event())
    assert result["created"]
    assert app.state.storage.overview()["backups"][0]["verified"]
    assert AutomaticBackup(app.state.storage, every_days=7, keep=4)(Event())["created"] is False


@pytest.mark.parametrize("sync_enabled", [False, True])
def test_app_starts_independent_backup_with_sync_disabled_or_offline(
    app_context, tmp_path, monkeypatch, sync_enabled
):
    _, app, _, _, _ = app_context
    checked, fetched = Event(), Event()

    class OfflineSource:
        def fetch(self, *args):
            fetched.set()
            raise ConnectionError("Simulated offline ActivityWatch")

    def check(self, every_days, keep):
        assert every_days == 7 and keep == 4
        checked.set()
        return None

    monkeypatch.setattr(StorageService, "backup_if_due", check)
    settings = app.state.settings.model_copy(
        update={
            "auto_sync_enabled": sync_enabled,
            "auto_backup_days": 7,
            "backup_dir": tmp_path / "background-backups",
        }
    )
    with TestClient(create_app(settings, source=OfflineSource())) as client:
        assert checked.wait(2)
        if sync_enabled:
            assert fetched.wait(2)
        status = client.get("/api/storage").json()["automatic_backup"]
        assert status["enabled"] and status["every_days"] == 7
        assert status["last_attempt_at"]
    assert not fetched.is_set() if not sync_enabled else fetched.is_set()


def test_backup_error_status_and_retry_are_independent_from_collection():
    calls, recovered = [], Event()

    def run(stop):
        calls.append(True)
        if len(calls) == 1:
            raise OSError("No space")
        recovered.set()
        return {"created": True}

    worker = PeriodicSync(run, 0.01, True, task="backup")
    worker.start()
    try:
        assert recovered.wait(2)
    finally:
        worker.stop()
    assert worker.snapshot()["last_error"] is None
    assert worker.snapshot()["last_result"] == {"created": True}
    assert worker.thread.name == "leisurelog-backup"
    assert not worker.thread.is_alive()


def test_backup_worker_observes_shutdown_without_creating_a_snapshot(app_context):
    _, app, _, _, _ = app_context
    stop = Event()
    stop.set()
    assert AutomaticBackup(app.state.storage, 7, 4)(stop) == {"created": False, "stopped": True}
    assert app.state.storage.overview()["backups"] == []
