"""Context-only updates must equal a full rebuild without reprocessing unrelated history."""

import json
import random
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, insert, select

from leisurelog.domain.classification import ClassificationPipeline
from leisurelog.domain.models import ActivityEvent, IdleEvent, IdleSourceRecord
from leisurelog.repositories.activity_context import SQLiteContext
from leisurelog.repositories.database import make_engine, session_factory
from leisurelog.repositories.models import (
    ActivityEventRow,
    Base,
    ContextOverrideRow,
    DailyActivityRow,
    RawEventRow,
    ResolvedEventRow,
    SessionEventRow,
    SessionRow,
)
from leisurelog.repositories.sqlite import SQLiteRepository
from leisurelog.services.activity_context import ActivityContextService
from leisurelog.services.processing import ProcessingService

pytest_plugins = ["tests.test_pipeline"]


def facts(db):
    return {
        model.__tablename__: sorted(
            json.dumps(dict(row), default=str, sort_keys=True)
            for row in db.execute(select(model.__table__)).mappings()
        )
        for model in (
            ActivityEventRow,
            ResolvedEventRow,
            SessionRow,
            SessionEventRow,
            DailyActivityRow,
        )
    }


@pytest.fixture
def seeded(tmp_path):
    engines = []

    def seed(windows, manual=None):
        engine = make_engine("sqlite:///" + (tmp_path / f"fixture-{len(engines)}.db").as_posix())
        engines.append(engine)
        Base.metadata.create_all(engine)
        db = session_factory(engine)()
        db.execute(
            insert(RawEventRow),
            [
                {
                    "id": n,
                    "event_id": value.id,
                    "source": value.source,
                    "stream": value.stream,
                    "source_event_id": value.id,
                    "payload_hash": value.id,
                    "payload": {},
                    "source_metadata": {},
                }
                for n, value in enumerate(windows, 1)
            ],
        )
        db.execute(
            insert(ActivityEventRow),
            [{**asdict(value), "raw_event_id": n} for n, value in enumerate(windows, 1)],
        )
        for key, purpose in (manual or {}).items():
            db.add(
                ContextOverrideRow(
                    event_id=key, window_event_id=key, assignments={"purpose": purpose}
                )
            )
        processor = ProcessingService(SQLiteRepository(db), ClassificationPipeline([]), 60)
        processor.rebuild()
        db.commit()
        return engine, db, processor, ActivityContextService(SQLiteContext(db), processor)

    yield seed
    for engine in engines:
        engine.dispose()


def windows(count, *, same=False):
    start = datetime(2026, 1, 1, 15, 50, tzinfo=timezone.utc)
    return [
        ActivityEvent(
            str(n),
            "fixture",
            "window",
            "synthetic",
            start + timedelta(seconds=n * 30),
            start + timedelta(seconds=(n + 1) * 30),
            "editor.exe",
            "same" if same else f"Synthetic {n % 7}",
        )
        for n in range(count)
    ]


def assert_full_equivalent(db, processor):
    db.flush()
    before = facts(db)
    processor.rebuild()
    assert facts(db) == before


def test_single_edit_never_reclassifies_or_expands_through_connected_history(seeded, monkeypatch):
    _, db, processor, context = seeded(windows(800))

    def forbidden(*args, **kwargs):
        pytest.fail("A context-only edit must not ingest, classify or plan a source rebuild")

    with monkeypatch.context() as patch:
        for name in ("processing_scope", "events", "browser_events", "save_classification"):
            patch.setattr(processor.repo, name, forbidden)
        patch.setattr(processor.pipeline, "for_processing", forbidden)
        context.attribute(["400"], {"purpose": "study"})
    assert processor.last_work["processed_events"] == 3
    assert processor.last_work["changed_contexts"] == 1
    assert_full_equivalent(db, processor)
    db.close()


def test_partial_session_splits_then_restores_and_can_merge_both_neighbours(seeded):
    _, db, processor, context = seeded(
        windows(18, same=True), {str(n): "study" if 6 <= n < 12 else "work" for n in range(18)}
    )
    context.attribute([str(n) for n in range(6, 12)], {"purpose": "work"})
    assert len(processor.repo.sessions()) == 1
    assert_full_equivalent(db, processor)
    context.attribute(["8", "9"], {"purpose": "study"})
    assert len(processor.repo.sessions()) == 3
    assert_full_equivalent(db, processor)
    context.restore(["8", "9"])
    assert_full_equivalent(db, processor)
    db.close()


@pytest.mark.parametrize("seed", range(5))
def test_overlaps_equal_start_times_devices_and_cross_midnight_equal_full_rebuild(seeded, seed):
    rng = random.Random(seed)
    start = datetime(2026, 1, 1, 15, 55, tzinfo=timezone.utc)
    values = [
        ActivityEvent(
            str(n),
            "fixture",
            f"window-{n % 2}",
            f"device-{n % 3}",
            start + timedelta(seconds=n // 12 * 15),
            start + timedelta(seconds=n // 12 * 15 + rng.choice([0, 15, 30, 60, 180])),
            rng.choice(["editor.exe", "browser.exe"]),
            rng.choice(["A", "B", "A"]),
        )
        for n in range(100)
    ]
    _, db, processor, context = seeded(values)
    available = [event.id for event in processor.repo.resolved_events()]
    for purpose in ["study", "work", "create"]:
        ids = rng.sample(available, 17)
        context.attribute(ids, {"purpose": purpose})
        assert_full_equivalent(db, processor)
    context.restore(ids)
    assert_full_equivalent(db, processor)
    db.close()


def test_batch_larger_than_sql_chunks_is_local_and_idempotent(seeded):
    engine, db, processor, context = seeded(windows(2500))
    statements = []

    def record(*args):
        statements.append(1)

    event.listen(engine, "before_cursor_execute", record)
    ids = [str(n * 2) for n in range(1000)]
    context.attribute(ids, {"purpose": "study"})
    assert processor.last_work["changed_contexts"] == 1000
    assert processor.last_work["processed_events"] < 2500
    assert len(statements) < 5000  # bounded writes, rather than repeated interval expansion
    event.remove(engine, "before_cursor_execute", record)
    assert_full_equivalent(db, processor)
    result = context.attribute(ids, {"purpose": "study"})
    assert result["change_id"] is None
    assert processor.last_work["processed_events"] == 0
    assert_full_equivalent(db, processor)
    db.close()


def test_disjoint_edits_keep_omitted_sessions_as_merge_barriers(seeded):
    values = windows(20, same=True)
    first = values[0].start_time
    values = [
        replace(
            value,
            start_time=first + timedelta(seconds=n * 2),
            end_time=first + timedelta(seconds=(n + 1) * 2),
        )
        for n, value in enumerate(values)
    ]
    _, db, processor, context = seeded(values, {"6": "study", "13": "study"})
    context.attribute(["2", "17"], {"purpose": "study"})
    assert_full_equivalent(db, processor)
    db.close()


def test_afk_and_manual_timing_survive_context_edit_and_restore(seeded):
    _, db, processor, context = seeded(windows(40, same=True))
    first = windows(1)[0].start_time
    for number, (start, end, status) in enumerate(
        [
            (0, 120, "not-afk"),
            (120, 900, "afk"),
            (900, 1200, "not-afk"),
        ]
    ):
        idle = IdleEvent(
            f"idle-{number}",
            "fixture",
            "afk",
            "synthetic",
            first + timedelta(seconds=start),
            first + timedelta(seconds=end),
            status,
        )
        processor.repo.ingest(IdleSourceRecord(idle, idle.id, {}, {}))
    processor.repo.set_timing_override("22", "foreground")
    processor.rebuild_changed()
    context.attribute(["18", "19", "22"], {"purpose": "study"})
    assert_full_equivalent(db, processor)
    context.restore(["18", "19", "22"])
    assert_full_equivalent(db, processor)
    db.close()


def test_failed_context_replacement_rolls_back_manual_and_derived_changes(app_context, monkeypatch):
    from leisurelog.repositories.context_processing import SQLiteContextProcessing
    from tests.test_pipeline import WINDOW

    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    with app.state.sessions() as db:
        before = facts(db)
        overrides = list(db.scalars(select(ContextOverrideRow)))

    def fail(*args):
        raise RuntimeError("synthetic context persistence failure")

    monkeypatch.setattr(SQLiteContextProcessing, "replace_sessions", fail)
    ids = [client.get("/api/events").json()[0]["id"]]
    with pytest.raises(RuntimeError, match="synthetic context persistence failure"):
        client.put("/api/events/context", json={"event_ids": ids, "purpose": "study"})
    with app.state.sessions() as db:
        assert facts(db) == before
        assert list(db.scalars(select(ContextOverrideRow))) == overrides
