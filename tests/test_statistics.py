from datetime import datetime, timedelta, timezone

import pytest
from alembic import command

from leisurelog.domain.daily import daily_activity
from leisurelog.domain.idle import apply_idle
from leisurelog.domain.models import ActivityEvent, IdleEvent
from leisurelog.domain.sessionization import merge_sessions
from leisurelog.repositories.sqlite import SQLiteRepository
from tests.test_pipeline import WINDOW

pytest_plugins = ["tests.test_pipeline"]


def test_range_cross_midnight_afk_and_correction(app_context):
    client, app, payloads, _, _ = app_context
    start = datetime(2026, 9, 29, 15, 59, tzinfo=timezone.utc)
    payloads[:] = [{**payloads[0], "timestamp": start.isoformat(), "duration": 120}]
    app.state.test_idle_payloads[:] = [
        {"id": 9, "timestamp": start.isoformat(), "duration": 120, "data": {"status": "not-afk"}},
        {
            "id": 10,
            "timestamp": (start + timedelta(seconds=30)).isoformat(),
            "duration": 90,
            "data": {"status": "afk"},
        },
    ]
    window = {"start": start.isoformat(), "end": (start + timedelta(minutes=5)).isoformat()}
    client.post("/api/sync/activitywatch", json=window).raise_for_status()
    result = client.get("/api/statistics?start=2026-09-28&end=2026-09-30").json()
    assert result["totals"]["recorded_seconds"] == 120
    assert result["totals"]["active_seconds"] == result["totals"]["leisure_seconds"] == 30
    assert result["totals"]["afk_seconds"] == 90
    assert result["totals"]["unverified_seconds"] == 0
    assert result["coverage"]["session_count"] == 1
    assert result["coverage"]["days_with_records"] == 2
    assert [row["active_seconds"] for row in result["trend"]] == [0, 30, 0]
    assert [row["has_records"] for row in result["trend"]] == [False, True, True]
    for day in ["2026-09-29", "2026-09-30"]:
        daily = client.get(f"/api/statistics?start={day}&end={day}").json()
        dashboard = client.get(f"/api/dashboard?day={day}").json()
        assert daily["totals"]["active_seconds"] == sum(
            dashboard["summary"]["active_seconds_by_category"].values()
        )
    event_id = client.get("/api/events").json()[0]["id"]
    client.put(
        f"/api/events/{event_id}/override", json={"category": "work", "content": "项目"}
    ).raise_for_status()
    corrected = client.get("/api/statistics?start=2026-01-01&end=2026-12-31").json()
    assert corrected["granularity"] == "month" and len(corrected["trend"]) == 12
    assert corrected["totals"]["work_seconds"] == 30 and corrected["totals"]["leisure_seconds"] == 0
    assert corrected["contents"][0]["content"] == "项目"
    assert corrected["trend"][8]["active_seconds"] == 30
    client.delete(f"/api/events/{event_id}/override").raise_for_status()
    assert (
        client.get("/api/statistics?start=2026-09-29&end=2026-09-30").json()["totals"][
            "leisure_seconds"
        ]
        == 30
    )


def test_union_gaps_and_unknown_device_daily_conservation():
    start = datetime(2026, 9, 29, 15, 59, 15, tzinfo=timezone.utc)
    events = [
        ActivityEvent("a", "aw", "window", "unknown", start, start + timedelta(seconds=15), "game"),
        ActivityEvent(
            "b",
            "aw",
            "window",
            "unknown",
            start + timedelta(seconds=60),
            start + timedelta(seconds=75),
            "game",
        ),
    ]
    idle = [IdleEvent("idle", "aw", "afk", "unknown", start, start + timedelta(seconds=90), "afk")]
    sessions = merge_sessions(events, 60)
    apply_idle(sessions, events, idle)
    records = daily_activity(sessions, events, idle)
    assert len(sessions) == 1 and len(records) == 2
    assert [r.recorded_seconds for r in records] == [15, 15]
    for field in ["recorded_seconds", "active_seconds", "afk_seconds", "unverified_seconds"]:
        assert sum(getattr(r, field) for r in records) == getattr(sessions[0], field)
    assert sum(r.unverified_seconds for r in records) == 30


def test_statistics_bounded_read_empty_validation_and_assets(app_context, monkeypatch):
    client, _, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()

    def no_history(*args):
        raise AssertionError("Analytics must use derived daily SQL aggregates")

    monkeypatch.setattr(SQLiteRepository, "events", no_history)
    monkeypatch.setattr(SQLiteRepository, "sessions", no_history)
    result = client.get("/api/statistics?start=2026-09-29&end=2026-09-29").json()
    assert result["totals"]["active_seconds"] == 120
    empty = client.get("/api/statistics?start=2025-01-01&end=2025-12-31").json()
    assert empty["coverage"]["days_with_records"] == 0
    assert empty["totals"]["active_seconds"] == 0
    assert all(not row["has_records"] for row in empty["trend"])
    assert client.get("/api/statistics?start=2026-09-30&end=2026-09-29").status_code == 422
    assert client.get("/api/statistics?start=2000-01-01&end=2026-09-29").status_code == 422
    assert client.get("/api/statistics?start=bad&end=2026-09-29").status_code == 422
    assert (
        client.get("/api/statistics?start=2026-09-29&end=2026-09-30&granularity=bad").status_code
        == 422
    )
    for path in ["/statistics", "/static/statistics.js", "/static/statistics.css"]:
        assert client.get(path).status_code == 200


def test_daily_write_failure_rolls_back_and_migration_rebuild(app_context, monkeypatch):
    client, _, _, _, migration = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    url = "/api/statistics?start=2026-09-29&end=2026-09-30"
    before = client.get(url).json()
    original = SQLiteRepository.replace_daily

    def fail_after_write(self, records, scope=None):
        original(self, records, scope)
        raise RuntimeError("simulated daily write failure")

    with monkeypatch.context() as patch:
        patch.setattr(SQLiteRepository, "replace_daily", fail_after_write)
        with pytest.raises(RuntimeError):
            client.post("/api/reprocess")
    assert client.get(url).json() == before
    command.downgrade(migration, "0004")
    command.upgrade(migration, "head")
    client.post("/api/reprocess").raise_for_status()
    assert client.get(url).json() == before
