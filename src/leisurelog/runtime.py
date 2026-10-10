"""Composition of the scheduled use case with persistence and configuration."""

import logging
from datetime import datetime, timedelta, timezone
from time import perf_counter

from sqlalchemy import text

from leisurelog.adapters.playnite import PlayniteUnavailable
from leisurelog.repositories.games import SQLiteGameCatalog
from leisurelog.repositories.models import SyncCheckpointRow
from leisurelog.repositories.sqlite import SQLiteRepository
from leisurelog.services.processing import ProcessingService

logger = logging.getLogger(__name__)


class AutomaticSync:
    def __init__(self, sessions, source, pipeline, settings, playnite=None, backup=None):
        self.sessions, self.source = sessions, source
        self.pipeline, self.settings = pipeline, settings
        self.playnite = playnite
        self.backup, self.backup_checked = backup, None

    def __call__(self, stop_event):
        began = perf_counter()
        totals = {"fetched": 0, "changed": 0, "windows": 0}
        work = {"processed_windows": 0, "incremental_runs": 0, "full_runs": 0, "unchanged_runs": 0}

        def track(svc):
            work["processed_windows"] += svc.last_work["processed_windows"]
            work[svc.last_work["mode"] + "_runs"] += 1

        # A missing or incomplete export must not interrupt ActivityWatch recording.
        if self.playnite is not None and not stop_event.is_set():
            try:
                payload, games = self.playnite.fetch()
            except PlayniteUnavailable:
                pass
            else:
                with self.sessions() as db:
                    db.execute(text("BEGIN IMMEDIATE"))
                    if SQLiteGameCatalog(db).replace(payload, games):
                        svc = ProcessingService(
                            SQLiteRepository(db), self.pipeline, self.settings.session_gap_seconds
                        )
                        svc.rebuild()
                        track(svc)
                    db.commit()
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
                changed = sum(repo.ingest(record) for record in records)
                svc = ProcessingService(
                    repo,
                    self.pipeline,
                    self.settings.session_gap_seconds,
                )
                result = svc.rebuild_changed()
                cursor = db.get(SyncCheckpointRow, "activitywatch")
                if cursor is None:
                    db.add(SyncCheckpointRow(source="activitywatch", last_success_end=window_end))
                else:
                    cursor.last_success_end = max(cursor.last_success_end, window_end)
                db.commit()
                track(svc)
            totals.update(events=result["events"], sessions=result["sessions"])
            totals["fetched"] += len(records)
            totals["changed"] += changed
            totals["windows"] += 1
            start = window_end
        self._maybe_backup()
        return {**totals, "processing": work, "duration_seconds": round(perf_counter() - began, 4)}

    def _maybe_backup(self):
        """At most hourly, after a sync: an automatic backup if one is due. Never fails a sync."""
        now = datetime.now(timezone.utc)
        if self.backup is None or (
            self.backup_checked and now - self.backup_checked < timedelta(hours=1)
        ):
            return
        self.backup_checked = now
        try:
            self.backup()
        except Exception:
            logger.exception("Automatic backup failed; will retry in an hour")
