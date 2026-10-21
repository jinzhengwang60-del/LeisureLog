"""Composition of the scheduled use case with persistence and configuration."""

from datetime import datetime, timedelta, timezone
from time import perf_counter

from sqlalchemy import text

from leisurelog.repositories.models import SyncCheckpointRow
from leisurelog.repositories.sqlite import SQLiteRepository
from leisurelog.services.processing import ProcessingService


class AutomaticSync:
    def __init__(self, sessions, source, pipeline, settings, before_sync=None):
        self.sessions, self.source = sessions, source
        self.pipeline, self.settings = pipeline, settings
        self.before_sync = before_sync

    def __call__(self, stop_event):
        began = perf_counter()
        totals = {"fetched": 0, "changed": 0, "windows": 0}
        work = {"processed_windows": 0, "incremental_runs": 0, "full_runs": 0, "unchanged_runs": 0}

        def track(svc):
            work["processed_windows"] += svc.last_work["processed_windows"]
            work[svc.last_work["mode"] + "_runs"] += 1

        # Optional metadata must never prevent the next core activity window.
        catalog_result = None
        if self.before_sync is not None and not stop_event.is_set():
            try:
                metadata = self.before_sync()
                catalog_result = {"status": "ok", "changed": bool(metadata.get("changed"))}
                if metadata.get("processing"):
                    work["processed_windows"] += metadata["processing"]["processed_windows"]
                    work[metadata["processing"]["mode"] + "_runs"] += 1
            except Exception:
                # Failure details belong to the plugin status, never private exception text.
                catalog_result = {"status": "unavailable"}
        end = datetime.now(timezone.utc)
        with self.sessions() as db:
            cursor = db.get(SyncCheckpointRow, "activitywatch")
            start = (
                cursor.last_success_end - timedelta(seconds=self.settings.auto_sync_overlap_seconds)
                if cursor
                else end - timedelta(hours=self.settings.auto_sync_initial_hours)
            )
        while start < end and not stop_event.is_set():
            window_end = min(start + timedelta(days=1), end)
            # Fetch before taking the SQLite writer lock. Other API writes remain responsive.
            records = self.source.fetch(start, window_end, None)
            with self.sessions() as db:
                db.execute(text("BEGIN IMMEDIATE"))
                repo = SQLiteRepository(db)
                svc = ProcessingService(
                    repo,
                    self.pipeline,
                    self.settings.session_gap_seconds,
                )
                result = svc.ingest(records)
                cursor = db.get(SyncCheckpointRow, "activitywatch")
                if cursor is None:
                    db.add(SyncCheckpointRow(source="activitywatch", last_success_end=window_end))
                else:
                    cursor.last_success_end = max(cursor.last_success_end, window_end)
                db.commit()
                track(svc)
            totals.update(events=result["events"], sessions=result["sessions"])
            totals["fetched"] += len(records)
            totals["changed"] += result["changed"]
            totals["windows"] += 1
            start = window_end
        return {
            **totals, "processing": work,
            "duration_seconds": round(perf_counter() - began, 4),
            **({"catalog": catalog_result} if catalog_result is not None else {}),
        }
