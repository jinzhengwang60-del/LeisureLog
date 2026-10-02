"""Differential checks against the full pipeline, including former interval bounds."""

import json
from dataclasses import asdict, replace
from datetime import timedelta

import pytest
from alembic import command
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import inspect, select, text

from leisurelog.analytics.query import day_sessions
from leisurelog.analytics.summary import summarize
from leisurelog.domain.browser import BrowserEvent, BrowserSourceRecord
from leisurelog.domain.models import (
    ActivityEvent,
    Classification,
    IdleEvent,
    IdleSourceRecord,
    SourceRecord,
)
from leisurelog.repositories.models import (
    ActivityEventRow,
    DailyActivityRow,
    ResolvedEventRow,
    SessionEventRow,
    SessionRow,
)
from leisurelog.repositories.sqlite import SQLiteRepository
from leisurelog.services.processing import ProcessingService
from tests.test_pipeline import START, WINDOW

pytest_plugins = ["tests.test_pipeline"]


def record(value):
    kind = (
        BrowserSourceRecord
        if isinstance(value, BrowserEvent)
        else IdleSourceRecord
        if isinstance(value, IdleEvent)
        else SourceRecord
    )
    return kind(value, value.id, json.loads(json.dumps(asdict(value), default=str)), {})


def activity(key, start=0, duration=50, **kwargs):
    return ActivityEvent(
        key,
        "activitywatch",
        "window",
        "pc",
        START + timedelta(seconds=start),
        START + timedelta(seconds=start + duration),
        "msedge.exe",
        "页面 - Microsoft Edge",
        **kwargs,
    )


def page(key="page", start=5, duration=150):
    return BrowserEvent(
        key,
        "activitywatch",
        "web",
        "pc",
        START + timedelta(seconds=start),
        START + timedelta(seconds=start + duration),
        ("msedge.exe",),
        "页面",
        "https://www.bilibili.com/video/BVtest",
        True,
    )


def idle(key="idle", start=0, duration=300, status="not-afk"):
    return IdleEvent(
        key,
        "activitywatch",
        "afk",
        "pc",
        START + timedelta(seconds=start),
        START + timedelta(seconds=start + duration),
        status,
    )


def service(app, db):
    return ProcessingService(SQLiteRepository(db), app.state.pipeline, 60)


def snapshot(db):
    result = {}
    for table in (
        ActivityEventRow,
        ResolvedEventRow,
        SessionRow,
        SessionEventRow,
        DailyActivityRow,
    ):
        columns = list(table.__table__.columns)
        rows = db.execute(select(*columns)).all()
        # Compare all persisted business fields, IDs and links, not just totals.
        result[table.__tablename__] = sorted(
            json.dumps(
                dict(zip([c.name for c in columns], r, strict=True)), sort_keys=True, default=str
            )
            for r in rows
        )
    return result


def initial(app, db):
    values = [
        activity("first"),
        activity("second", 90),
        activity("third", 180),
        activity("later", 86400),
        activity("old", -366 * 86400),
        replace(activity("other"), device="other"),
        activity("cross-midnight", 16 * 3600 - 60, 180),
        page(),
        idle(),
    ]
    svc = service(app, db)
    for value in values:
        svc.repo.ingest(record(value))
    svc.rebuild()
    db.commit()
    return {v.id: v for v in values}


@pytest.mark.parametrize(
    "change",
    [
        "extend",
        "shrink",
        "zero",
        "move-time",
        "move-device",
        "move-stream",
        "change-app",
        "bridge",
        "browser-boundary",
        "browser-url",
        "browser-conflict",
        "browser-device",
        "afk",
        "afk-shrink",
        "afk-move",
        "afk-midnight",
        "cross-midnight",
    ],
)
def test_incremental_matches_full_for_source_changes(app_context, change):
    _, app, _, _, _ = app_context
    with app.state.sessions() as db:
        values = initial(app, db)
        before_old = db.get(
            SessionRow, next(s.id for s in SQLiteRepository(db).sessions() if "old" in s.event_ids)
        ).active_seconds
        first = values["first"]
        choices = {
            "extend": replace(first, end_time=START + timedelta(seconds=160)),
            "shrink": replace(first, end_time=START + timedelta(seconds=1)),
            "zero": replace(first, end_time=first.start_time),
            "move-time": replace(
                first,
                start_time=START + timedelta(days=1),
                end_time=START + timedelta(days=1, seconds=100),
            ),
            "move-device": replace(first, device="other"),
            "move-stream": replace(first, stream="another-window"),
            "change-app": replace(first, app="test.exe", title="changed"),
            "bridge": activity("bridge", 130, 80),
            "browser-boundary": replace(page(), start_time=START + timedelta(seconds=10)),
            "browser-url": replace(page(), url="https://example.com"),
            "browser-conflict": replace(page("conflict"), url="https://example.com"),
            "browser-device": replace(page(), device="other"),
            "afk": replace(idle(), status="afk"),
            "afk-shrink": idle(duration=10),
            "afk-move": idle(start=86400, duration=200, status="afk"),
            "afk-midnight": idle("midnight-afk", 16 * 3600 - 30, 100, "afk"),
            "cross-midnight": replace(
                values["cross-midnight"], end_time=START + timedelta(hours=17)
            ),
        }
        svc = service(app, db)
        assert svc.repo.ingest(record(choices[change]))
        result = svc.rebuild_changed()
        assert svc.last_work["mode"] == "incremental"
        assert svc.last_work["processed_windows"] < result["events"]
        incremental = snapshot(db)
        assert (
            next(s for s in svc.repo.sessions() if "old" in s.event_ids).active_seconds
            == before_old
        )
        svc.rebuild()
        assert snapshot(db) == incremental


@pytest.mark.parametrize(
    "action", ["root", "segment", "clear", "timing", "timing-clear", "learn-rule"]
)
def test_incremental_corrections_equal_full_and_keep_priority(app_context, action):
    _, app, _, _, _ = app_context
    with app.state.sessions() as db:
        initial(app, db)
        svc = service(app, db)
        segment = next(
            e
            for e in svc.repo.resolved_events(ids=None)
            if e.window_event_id == "first" and e.browser_event_id
        )
        manual = Classification("work", "人工内容", ("自定义",), "manual")
        if action == "root":
            svc.override("first", manual)
        elif action == "clear":
            svc.override("first", manual)
            svc.override_many([segment.id], None)
        elif action == "timing":
            svc.timing_many([segment.id], "foreground")
        elif action == "timing-clear":
            svc.timing_many([segment.id], "foreground")
            svc.timing_many([segment.id], None)
        else:
            svc.override_many([segment.id], manual, "domain" if action == "learn-rule" else None)
        assert svc.last_work["mode"] == ("full" if action == "learn-rule" else "incremental")
        incremental = snapshot(db)
        svc.rebuild()
        assert snapshot(db) == incremental


def test_no_change_sync_does_not_write_derived_rows(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()

    def fail(*args, **kwargs):
        raise AssertionError("Unchanged telemetry must not read or rewrite history")

    for name in [
        "events",
        "browser_events",
        "idle_events",
        "overrides",
        "save_resolved",
        "replace_sessions",
        "replace_daily",
        "prune_resolved",
    ]:
        monkeypatch.setattr(SQLiteRepository, name, fail)
    assert client.post("/api/sync/activitywatch", json=WINDOW).json() == {
        "fetched": 2,
        "changed": 0,
        "events": 2,
        "sessions": 1,
    }
    with app.state.sessions() as db:
        svc = service(app, db)
        assert svc.rebuild_changed() == {"events": 2, "sessions": 1}
        assert svc.last_work["processed_windows"] == 0


def test_partial_writes_leave_unaffected_rows_untouched(app_context):
    _, app, _, _, _ = app_context
    with app.state.sessions() as db:
        initial(app, db)
        old = next(s for s in SQLiteRepository(db).sessions() if "old" in s.event_ids)
        # Triggers detect even delete-and-reinsert with identical final values.
        db.execute(text("CREATE TABLE audit (item TEXT)"))
        for table in ("sessions", "session_events", "daily_activity"):
            key = "id" if table == "sessions" else "session_id"
            db.execute(
                text(f"""CREATE TRIGGER audit_{table} BEFORE DELETE ON {table}
                WHEN OLD.{key} = '{old.id}' BEGIN INSERT INTO audit VALUES ('deleted'); END""")
            )
        svc = service(app, db)
        svc.override("first", Classification("work", origin="manual"))
        assert db.execute(text("SELECT count(*) FROM audit")).scalar_one() == 0


def test_bounded_reads_paging_and_sql_summaries(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    with app.state.sessions() as db:
        initial(app, db)
        expected_summary = summarize(SQLiteRepository(db).sessions())
        expected_events = SQLiteRepository(db).resolved_events()[1:3]
        expected_sessions = SQLiteRepository(db).sessions()[1:3]
        expected_idle = SQLiteRepository(db).idle_events()[0:1]
        expected_day = day_sessions(SQLiteRepository(db), START.date())
    observed = []
    for name in ["events", "browser_events", "resolved_events", "sessions", "idle_events"]:
        original = getattr(SQLiteRepository, name)

        def bounded(self, _name=name, _original=original, **filters):
            assert filters, f"Unbounded history read: {_name}"
            observed.append((_name, filters))
            return _original(self, **filters)

        monkeypatch.setattr(SQLiteRepository, name, bounded)

    def encoded(values):
        return json.loads(json.dumps([asdict(e) for e in values], default=lambda v: v.isoformat()))

    assert client.get("/api/events?offset=1&limit=2").json() == encoded(expected_events)
    assert client.get("/api/sessions?offset=1&limit=2").json() == encoded(expected_sessions)
    assert client.get("/api/idle-events?limit=1").json() == encoded(expected_idle)
    assert client.get("/api/stats/summary").json() == expected_summary
    assert client.get("/api/browser/status").status_code == 200
    dashboard = client.get("/api/dashboard?day=2026-09-29").json()
    assert dashboard["summary"] == summarize(expected_day[0])
    details = client.get(f"/api/sessions/{expected_day[0][0].id}/details?day=2026-09-29")
    assert details.status_code == 200
    assert any("ids" in filters for _, filters in observed)


def test_index_migration_roundtrip_preserves_all_data(app_context):
    _, app, _, _, migration = app_context
    with app.state.sessions() as db:
        initial(app, db)
        before = snapshot(db)
    command.downgrade(migration, "0010")
    command.upgrade(migration, "head")
    with app.state.sessions() as db:
        assert snapshot(db) == before
        inspector = inspect(db.bind)
        for table in ["activity_events", "sessions", "browser_events", "idle_events"]:
            assert f"ix_{table}_processing" in {r["name"] for r in inspector.get_indexes(table)}


def test_scoped_failure_rolls_back_raw_and_all_derived(app_context):
    _, app, _, _, _ = app_context
    with app.state.sessions() as db:
        values = initial(app, db)
        before = snapshot(db)
        svc = service(app, db)
        svc.repo.ingest(record(replace(values["first"], end_time=START + timedelta(seconds=80))))

        def fail(*args):
            raise RuntimeError("daily failure after partial Session replacement")

        svc.repo.replace_daily = fail
        with pytest.raises(RuntimeError):
            svc.rebuild_changed()
        db.rollback()
        assert snapshot(db) == before


def test_local_scope_reads_only_affected_objects(app_context):
    _, app, _, _, _ = app_context
    with app.state.sessions() as db:
        initial(app, db)
        svc = service(app, db)
        queries = []

        def capture(connection, cursor, statement, parameters, context, many):
            if "SELECT" in statement and "FROM activity_events" in statement:
                queries.append(statement)

        sqlalchemy_event.listen(db.bind, "before_cursor_execute", capture)
        try:
            svc.override("first", Classification("work", origin="manual"))
        finally:
            sqlalchemy_event.remove(db.bind, "before_cursor_execute", capture)
        assert svc.last_work["processed_windows"] == 3
        assert all("WHERE" in q for q in queries if "count(*)" not in q)


def test_scheduled_sync_reports_incremental_and_unchanged_work(app_context, monkeypatch):
    from datetime import datetime, timezone
    from threading import Event

    from leisurelog.repositories.models import SyncCheckpointRow
    from leisurelog.runtime import AutomaticSync

    _, app, payloads, _, _ = app_context
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    for n, payload in enumerate(payloads):
        payload["timestamp"] = (now + timedelta(seconds=n * 90)).isoformat()
    runner = AutomaticSync(
        app.state.sessions, app.state.source, app.state.pipeline, app.state.settings
    )
    first = runner(Event())
    assert first["processing"] == {
        "processed_windows": 2,
        "incremental_runs": 1,
        "full_runs": 0,
        "unchanged_runs": 0,
    }
    with app.state.sessions() as db:
        checkpoint = db.get(SyncCheckpointRow, "activitywatch").last_success_end

    def no_rebuild(*args, **kwargs):
        raise AssertionError("Scheduled unchanged sync must skip all derived writes")

    with monkeypatch.context() as patch:
        patch.setattr(SQLiteRepository, "replace_sessions", no_rebuild)
        unchanged = runner(Event())
    assert unchanged["processing"] == {
        "processed_windows": 0,
        "incremental_runs": 0,
        "full_runs": 0,
        "unchanged_runs": 1,
    }
    with app.state.sessions() as db:
        assert db.get(SyncCheckpointRow, "activitywatch").last_success_end >= checkpoint
    payloads[0]["duration"] = 80
    assert runner(Event())["processing"]["incremental_runs"] == 1


def test_fragmented_bulk_import_falls_back_without_sql_limits(app_context):
    _, app, _, _, _ = app_context
    with app.state.sessions() as db:
        svc = service(app, db)
        for day in range(150):
            svc.repo.ingest(record(activity(f"day-{day}", day * 86400)))
        result = svc.rebuild_changed()
        assert result == {"events": 150, "sessions": 150}
        assert svc.last_work["mode"] == "full"
        assert len(svc.repo.resolved_events()) == 150
        before = snapshot(db)
        svc.rebuild()
        assert snapshot(db) == before
