"""Installation lifecycle tests use only isolated synthetic user profiles."""

import json
import socket
import sqlite3
from zipfile import ZipFile

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from leisurelog import DATABASE_REVISION
from leisurelog.desktop.application import desktop_app
from leisurelog.desktop.database import (
    database_revision,
    migration_config,
    prepare_database,
)
from leisurelog.desktop.instance import InstanceLock
from leisurelog.desktop.launcher import reserve_socket
from leisurelog.desktop.paths import DesktopPaths
from leisurelog.desktop.profile import DesktopPreferences


@pytest.fixture
def user_paths(tmp_path):
    paths = DesktopPaths(tmp_path / "试用用户 100%" / "LeisureLog")
    paths.prepare()
    return paths


def test_desktop_ignores_cwd_and_inherited_developer_environment(user_paths, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("LEISURELOG_DATABASE_URL=sqlite:///private.db", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LEISURELOG_DATABASE_URL", "sqlite:///do-not-use.db")
    monkeypatch.setenv("LEISURELOG_RULES_PATH", "private-rules.yaml")
    monkeypatch.setenv("LEISURELOG_BROWSER_DEVICE_BINDINGS", "not-valid-json")
    settings = DesktopPreferences().settings(user_paths)
    assert make_url(settings.database_url).database == str(user_paths.database)
    assert settings.rules_path == user_paths.config / "rules.yaml"
    assert not settings.auto_sync_enabled
    assert settings.browser_device_bindings == {}
    assert prepare_database(user_paths)["to"] == DATABASE_REVISION
    assert not (tmp_path / "do-not-use.db").exists()
    assert not (tmp_path / "private.db").exists()


def test_new_database_and_user_rules_survive_repeated_startup(user_paths):
    result = prepare_database(user_paths)
    assert result["from"] is None and result["backup"] is None
    rules = user_paths.config / "rules.yaml"
    rules.write_text("rules: []\n# my custom rules\n", encoding="utf-8")
    preferences = DesktopPreferences(setup_completed=True, sync_enabled=False)
    preferences.save(user_paths)
    user_paths.prepare()
    assert "my custom rules" in rules.read_text(encoding="utf-8")
    assert "bindings: []" in (user_paths.config / "playnite-processes.yaml").read_text()
    assert prepare_database(user_paths)["from"] == DATABASE_REVISION
    assert not DesktopPreferences.load(user_paths).sync_enabled


def test_old_database_is_backed_up_before_upgrade(user_paths):
    config = migration_config(user_paths.database)
    command.upgrade(config, "0012")
    with sqlite3.connect(user_paths.database) as db:
        db.execute("CREATE TABLE installation_probe (value TEXT)")
        db.execute("INSERT INTO installation_probe VALUES ('synthetic-record')")
    result = prepare_database(user_paths)
    assert result["from"] == "0012"
    assert database_revision(user_paths.database) == DATABASE_REVISION
    with sqlite3.connect(result["backup"]) as backup, sqlite3.connect(user_paths.database) as db:
        assert backup.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0012"
        assert (
            db.execute("SELECT value FROM installation_probe").fetchone()[0] == "synthetic-record"
        )


def test_failed_upgrade_restores_the_previous_database(user_paths, monkeypatch):
    command.upgrade(migration_config(user_paths.database), "0012")

    def fail(config, revision):
        with sqlite3.connect(user_paths.database) as db:
            db.execute("CREATE TABLE partial_upgrade (value TEXT)")
            db.execute("UPDATE alembic_version SET version_num='broken'")
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(command, "upgrade", fail)
    with pytest.raises(RuntimeError, match="升级失败"):
        prepare_database(user_paths)
    assert database_revision(user_paths.database) == "0012"
    with sqlite3.connect(user_paths.database) as db:
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='partial_upgrade'"
        ).fetchall()


def test_unknown_database_revision_is_not_modified(user_paths):
    prepare_database(user_paths)
    with sqlite3.connect(user_paths.database) as db:
        db.execute("UPDATE alembic_version SET version_num='9999'")
    with pytest.raises(Exception, match="9999"):
        prepare_database(user_paths)
    assert database_revision(user_paths.database) == "9999"


def test_single_instance_lock_is_per_user_profile_and_released(user_paths, tmp_path):
    first = InstanceLock(user_paths.root)
    second = InstanceLock(user_paths.root)
    other = InstanceLock(tmp_path / "another-user")
    try:
        assert first.acquire()
        assert not second.acquire()
        assert other.acquire()
        first.close()
        assert second.acquire()
    finally:
        if not first.file.closed:
            first.close()
        second.close()
        other.close()


def test_reserved_socket_handles_an_occupied_port():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        with reserve_socket(occupied.getsockname()[1]) as available:
            assert available.getsockname()[0] == "127.0.0.1"
            assert available.getsockname()[1] != occupied.getsockname()[1]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:5600",
        "http://example.com:5600",
        "http://localhost:5600/remote",
        "http://user:password@localhost:5600",
        "http://localhost:5600?data=1",
    ],
)
def test_activitywatch_configuration_remains_local(url):
    with pytest.raises(ValueError):
        DesktopPreferences(activitywatch_url=url)


def test_onboarding_authentication_source_checks_and_private_playnite_package(user_paths):
    prepare_database(user_paths)
    reads, exits = [], []

    class Source:
        def fetch(self, *args):
            reads.append(True)
            return []

    token, origin = "test-desktop-secret", "http://127.0.0.1:18765"
    app = desktop_app(
        user_paths, DesktopPreferences(), token, origin, lambda: exits.append(True), source=Source()
    )
    with TestClient(app, base_url=origin) as client:
        assert client.get("/_desktop/status").status_code == 401
        assert client.get("/api/events").status_code == 401
        assert not reads
        assert client.get("/_desktop/open?token=wrong").status_code == 401
        assert client.get("/_desktop/open?token=中文").status_code == 401
        response = client.get(f"/_desktop/open?token={token}")
        assert response.url.path == "/setup" and "token" not in str(response.url)
        assert (
            "HttpOnly"
            in client.get(f"/_desktop/open?token={token}", follow_redirects=False).headers[
                "set-cookie"
            ]
        )
        assert client.get("/setup").status_code == 200
        assert client.post("/api/reprocess").status_code == 409
        assert client.post("/_desktop/setup", json={"consent": False}).status_code == 422
        assert not reads
        assert (
            client.post(
                "/_desktop/setup",
                json={"consent": True},
                headers={"Origin": "https://unrelated.example"},
            ).status_code
            == 403
        )
        assert (
            client.get("/_desktop/status", headers={"Host": "unrelated.example"}).status_code == 403
        )
        assert (
            client.get("/_desktop/status", headers={"Sec-Fetch-Site": "cross-site"}).status_code
            == 403
        )
        assert (
            client.post("/_desktop/setup", json={"consent": True, "initial_hours": 1}).status_code
            == 200
        )
        assert DesktopPreferences.load(user_paths).setup_completed
        assert client.get("/_desktop/status").json()["sync"]["enabled"]
        assert client.get(f"/_desktop/open?token={token}&page=setup").url.path == "/setup"
        assert client.post("/_desktop/sync", json={"enabled": False}).status_code == 200
        assert not client.get("/_desktop/status").json()["sync"]["enabled"]
        assert not DesktopPreferences.load(user_paths).sync_enabled
        assert client.get("/_desktop/playnite.pext").status_code == 200
        with ZipFile(user_paths.root / "data/LeisureLog-Playnite.pext") as archive:
            destination = json.loads(archive.read("settings.json"))["export_path"]
            assert destination == str(user_paths.root / "data/playnite-library.json")
            assert archive.read("LeisureLog.psm1").startswith(b"\xef\xbb\xbf")
        assert client.post("/_desktop/shutdown").json()["stopping"]
        assert exits == [True]
