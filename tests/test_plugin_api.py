"""Host lifecycle through real FastAPI and isolated SQLite, including core collection."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from leisurelog.adapters.plugin_manifest import read_plugin_manifest
from leisurelog.config import Settings
from leisurelog.domain.models import ActivityEvent, Classification, SourceRecord
from leisurelog.domain.plugin_contracts import ActivitySummary, SummaryQuery
from leisurelog.domain.plugin_runtime import PluginContributions, PluginDefinition
from leisurelog.domain.plugins import PluginCapability as Capability
from leisurelog.domain.plugins import PluginPermission as Permission
from leisurelog.main import create_app
from leisurelog.repositories.models import RawEventRow
from leisurelog.repositories.plugin_summary import SQLitePluginSummary
from leisurelog_plugins.diagnostics import create as diagnostic_factory
from tests.test_plugin_runtime import definition, eventually, status

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 10, 14, 1, tzinfo=timezone.utc)
WINDOW = {"start": START.isoformat(), "end": (START + timedelta(hours=1)).isoformat()}


class Source:
    def fetch(self, start, end, buckets):
        event = ActivityEvent(
            "sample:1",
            "synthetic",
            "window",
            "pc",
            START,
            START + timedelta(seconds=60),
            "synthetic.exe",
            "private window",
        )
        return [SourceRecord(event, "1", {"app": event.app, "title": event.title}, {})]


@pytest.fixture
def application(tmp_path, monkeypatch):
    database_url = "sqlite:///" + (tmp_path / "activity.db").as_posix()
    monkeypatch.setenv("LEISURELOG_DATABASE_URL", database_url)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    rules = tmp_path / "rules.yaml"
    rules.write_text("rules: []\n", encoding="utf-8")
    settings = Settings(
        database_url=database_url,
        rules_path=rules,
        auto_sync_enabled=False,
        auto_backup_days=0,
        playnite_export_path=tmp_path / "not-installed.json",
        plugin_state_path=tmp_path / "config" / "plugins.json",
    )

    def create(plugins=()):
        return create_app(settings, Source(), plugins=plugins)

    create.settings = settings
    return create


def test_default_application_has_empty_plugin_host_and_cannot_import_from_request(application):
    app = application()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/plugins").json()["plugins"] == []
        response = client.post("/api/plugins/example.missing/enable", json={})
        assert response.status_code == 404
        assert (
            client.post(
                "/api/plugins/example.missing/enable", json={"module": "arbitrary.py"}
            ).status_code
            == 422
        )
        assert client.post("/api/sync/activitywatch", json=WINDOW).json()["changed"] == 1
        assert not application.settings.plugin_state_path.exists()


def test_official_diagnostic_uses_real_summary_and_restores_saved_choice(application):
    manifest = read_plugin_manifest(ROOT / "integrations/plugins/examples/diagnostics.json")
    plugin = PluginDefinition(manifest, diagnostic_factory)
    app = application((plugin,))
    with TestClient(app) as client:
        denied = client.post("/api/plugins/leisurelog.diagnostics/enable", json={})
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "permission_required"
        enabled = client.post(
            "/api/plugins/leisurelog.diagnostics/enable",
            json={
                "grants": {"leisurelog.diagnostics": ["activity.summary.read"]},
                "expected_revision": 0,
            },
        )
        assert enabled.status_code == 200, enabled.text
        eventually(
            lambda: any(
                value["completed_runs"]
                for value in status(app.state.plugins, "leisurelog.diagnostics")["workers"]
                if value["kind"] == "task"
            )
        )
        client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
        provider = SQLitePluginSummary(app.state.sessions)
        summary = provider.read(SummaryQuery(date(2020, 1, 1), date(2026, 12, 31)))
        assert summary.total_active_seconds == 60
        assert summary.by_category[0].category == "unknown"
        assert provider.read(SummaryQuery(date(2026, 1, 1), date(2026, 1, 2))) == ActivitySummary(0)
        assert provider.read(
            SummaryQuery(date(2020, 1, 1), date(2026, 12, 31), project_id="missing-project")
        ) == ActivitySummary(0)
        assert "private window" not in client.get("/api/plugins").text
    resumed = application((plugin,))
    with TestClient(resumed) as client:
        assert status(resumed.state.plugins, "leisurelog.diagnostics")["state"] == "running"
        response = client.delete(
            "/api/plugins/leisurelog.diagnostics/permissions/activity.summary.read"
        )
        assert response.status_code == 200
        assert status(resumed.state.plugins, "leisurelog.diagnostics")["state"] == "disabled"
        assert not status(resumed.state.plugins, "leisurelog.diagnostics")["enabled"]


@pytest.mark.parametrize("failure", ["raise", "invalid", "timeout"])
def test_bad_classifier_does_not_abort_core_ingestion(application, failure):
    release = Event()

    def classify(event):
        if failure == "raise":
            raise RuntimeError(event.title)
        if failure == "timeout":
            release.wait(2)
            return Classification("work", "late")
        return {"invalid": True}

    plugin = definition(
        caps=(Capability.CLASSIFIER,),
        permissions=(Permission.DETAILS_READ, Permission.CLASSIFICATION_PROPOSE),
        create=lambda context: PluginContributions(
            classifiers=(SimpleNamespace(classify=classify),)
        ),
    )
    app = application((plugin,))
    try:
        with TestClient(app) as client:
            client.post(
                "/api/plugins/example.test/enable",
                json={
                    "grants": {
                        "example.test": ["activity.details.read", "classification.propose"],
                    }
                },
            ).raise_for_status()
            result = client.post("/api/sync/activitywatch", json=WINDOW)
            assert result.status_code == 200, result.text
            assert result.json()["changed"] == 1
            assert len(client.get("/api/sessions").json()) == 1
            assert status(app.state.plugins)["state"] == "failed"
            assert client.get("/health").status_code == 200
            with app.state.sessions() as db:
                assert db.scalar(select(func.count()).select_from(RawEventRow)) == 1
            assert "private window" not in client.get("/api/plugins").text
            # The next scheduled source pass still succeeds with the failed plugin withdrawn.
            result = app.state.scheduler.run(Event())
            assert result["fetched"] >= 1
            release.set()
    finally:
        release.set()


def test_live_classifier_survives_rule_reload_and_manual_override_remains_first(application):
    calls = []
    plugin = definition(
        caps=(Capability.CLASSIFIER,),
        permissions=(Permission.DETAILS_READ, Permission.CLASSIFICATION_PROPOSE),
        create=lambda context: PluginContributions(
            classifiers=(
                SimpleNamespace(
                    classify=lambda event: (
                        calls.append(event) or Classification("work", "Plugin", origin="manual")
                    ),
                ),
            )
        ),
    )
    app = application((plugin,))
    with TestClient(app) as client:
        client.post(
            "/api/plugins/example.test/enable",
            json={
                "grants": {
                    "example.test": ["activity.details.read", "classification.propose"],
                }
            },
        ).raise_for_status()
        client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
        event = client.get("/api/events").json()[0]
        assert event["classification"]["origin"] == "plugin:example.test@0.1.0"
        assert all(type(value) is ActivityEvent for value in calls)
        client.post("/api/classification/reload-rules").raise_for_status()
        assert app.state.plugins in app.state.pipeline.classifiers
        before = len(calls)
        client.put(
            f"/api/events/{event['id']}/override", json={"category": "game"}
        ).raise_for_status()
        assert len(calls) == before
        assert client.get("/api/events").json()[0]["classification"]["origin"] == "manual"


def test_corrupt_plugin_config_preserves_core_collection(application):
    path = application.settings.plugin_state_path
    path.parent.mkdir(parents=True)
    path.write_text("invalid JSON", encoding="utf-8")
    with TestClient(application()) as client:
        assert (
            client.get("/api/plugins").json()["configuration_error"]["code"]
            == "configuration_invalid"
        )
        assert client.post("/api/sync/activitywatch", json=WINDOW).status_code == 200
        assert client.get("/health").status_code == 200
        assert path.read_text(encoding="utf-8") == "invalid JSON"
