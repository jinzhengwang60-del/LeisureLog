"""Reproducible multi-year benchmark in a disposable database, never the user's DB."""

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from sqlalchemy import insert, select

from leisurelog.adapters.rules import RuleClassifier
from leisurelog.domain.classification import ClassificationPipeline
from leisurelog.domain.models import ActivityEvent, SourceRecord
from leisurelog.repositories.database import make_engine, session_factory
from leisurelog.repositories.models import (
    ActivityEventRow,
    Base,
    DailyActivityRow,
    RawEventRow,
    ResolvedEventRow,
    SessionEventRow,
    SessionRow,
)
from leisurelog.repositories.sqlite import SQLiteRepository
from leisurelog.services.processing import ProcessingService


def derived_fingerprint(db):
    result = {}
    for table in (
        ActivityEventRow,
        ResolvedEventRow,
        SessionRow,
        SessionEventRow,
        DailyActivityRow,
    ):
        rows = [
            json.dumps(dict(r), sort_keys=True, default=str)
            for r in db.execute(select(table.__table__)).mappings()
        ]
        result[table.__tablename__] = hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()
    return result


def run(days, per_day):
    with TemporaryDirectory(prefix="leisurelog-benchmark-") as folder:
        engine = make_engine("sqlite:///" + (Path(folder) / "benchmark.db").as_posix())
        try:
            Base.metadata.create_all(engine)
            sessions = session_factory(engine)
            first = datetime(2023, 1, 1, tzinfo=timezone.utc)
            raw, windows = [], []
            for day in range(days):
                for n in range(per_day):
                    number = len(windows) + 1
                    start = first + timedelta(days=day, seconds=n * 330)
                    value = ActivityEvent(
                        str(number),
                        "benchmark",
                        "window",
                        "fixture-pc",
                        start,
                        start + timedelta(seconds=300),
                        "GenshinImpact.exe",
                    )
                    raw.append(
                        {
                            "id": number,
                            "event_id": value.id,
                            "source": value.source,
                            "stream": value.stream,
                            "source_event_id": value.id,
                            "payload_hash": str(number),
                            "payload": {},
                            "source_metadata": {},
                        }
                    )
                    windows.append({**asdict(value), "raw_event_id": number})
            with sessions() as db:
                db.execute(insert(RawEventRow), raw)
                db.execute(insert(ActivityEventRow), windows)
                db.commit()
                rules = RuleClassifier(Path(__file__).resolve().parents[1] / "config/rules.yaml")
                svc = ProcessingService(SQLiteRepository(db), ClassificationPipeline([rules]), 60)
                start = perf_counter()
                baseline = svc.rebuild()
                db.commit()
                full_seconds = perf_counter() - start
                value = ActivityEvent(
                    **{
                        k: v
                        for k, v in windows[-1].items()
                        if k not in ("raw_event_id", "classification")
                    }
                )
                from dataclasses import replace

                value = replace(value, end_time=value.end_time + timedelta(seconds=10))
                revision = SourceRecord(value, value.id, {"duration": 310}, {})
                start = perf_counter()
                assert svc.repo.ingest(revision)
                result = svc.rebuild_changed()
                db.commit()
                incremental_seconds = perf_counter() - start
                work = svc.last_work.copy()
                assert work["processed_windows"] == per_day
                incremental = derived_fingerprint(db)
                svc.rebuild()
                db.commit()
                assert derived_fingerprint(db) == incremental
                start = perf_counter()
                assert not svc.repo.ingest(revision)
                svc.rebuild_changed()
                db.commit()
                unchanged_seconds = perf_counter() - start
                return {
                    "fixture": {
                        "days": days,
                        "windows_per_day": per_day,
                        "total_windows": baseline["events"],
                    },
                    "full_rebuild_seconds": round(full_seconds, 4),
                    "incremental_heartbeat_seconds": round(incremental_seconds, 4),
                    "unchanged_sync_seconds": round(unchanged_seconds, 4),
                    "speedup_on_this_fixture": round(full_seconds / incremental_seconds, 2),
                    "incremental_work": work,
                    "result_counts": result,
                    "full_and_incremental_equal": True,
                    "unchanged_processed_windows": svc.last_work["processed_windows"],
                    "limitations": "One sample on this machine; connected periods can be larger. "
                    "No production database used; temporary data removed on exit.",
                }
        finally:
            engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=1096)
    parser.add_argument("--events-per-day", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.days <= 10000 or not 1 <= args.events_per_day <= 200:
        parser.error("days must be 1..10000 and events-per-day 1..200")
    result = run(args.days, args.events_per_day)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized)
