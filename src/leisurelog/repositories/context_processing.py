"""Bounded persistence for context-only edits; no source ingestion or classification."""

from dataclasses import asdict

from sqlalchemy import delete, select, tuple_, update

from leisurelog.domain.processing import context_neighborhood
from leisurelog.repositories.models import (
    DailyActivityRow,
    ResolvedEventRow,
    SessionEventRow,
    SessionRow,
)


def chunks(values):
    values = sorted(values)
    for start in range(0, len(values), 500):
        yield values[start : start + 500]


class SQLiteContextProcessing:
    def __init__(self, db):
        self.db = db

    def events(self, window_ids):
        for batch in chunks(window_ids):
            yield from self.db.scalars(
                select(ResolvedEventRow).where(ResolvedEventRow.window_event_id.in_(batch))
            )

    def save_contexts(self, events):
        values = [{"id": event.id, "context": asdict(event.context)} for event in events]
        if values:
            self.db.execute(update(ResolvedEventRow), values)
            self.db.flush()

    def session_groups(self, changed_ids):
        row = ResolvedEventRow
        streams = set()
        for batch in chunks(changed_ids):
            streams.update(
                self.db.execute(
                    select(row.source, row.device, row.stream).where(row.id.in_(batch)).distinct()
                )
            )
        result = []
        # Only ordering metadata is read from the stream; other activity payloads stay unloaded.
        for batch in chunks(streams):
            membership = self.db.execute(
                select(
                    row.source,
                    row.device,
                    row.stream,
                    SessionEventRow.session_id,
                    row.id,
                    row.start_time,
                    row.end_time,
                )
                .join(SessionEventRow, row.id == SessionEventRow.event_id)
                .where(tuple_(row.source, row.device, row.stream).in_(batch))
                .order_by(row.source, row.device, row.stream, row.start_time, row.end_time, row.id)
            )
            result.extend(context_neighborhood(membership, changed_ids))
        return result

    def session_events(self, session_ids):
        for batch in chunks(session_ids):
            yield from self.db.execute(
                select(SessionEventRow.session_id, ResolvedEventRow)
                .join(SessionEventRow, ResolvedEventRow.id == SessionEventRow.event_id)
                .where(SessionEventRow.session_id.in_(batch))
            )

    def replace_sessions(self, sessions, old_ids, daily):
        # Exact IDs avoid touching other interleaved/overlapping Sessions.
        for batch in chunks(old_ids):
            for table in (DailyActivityRow, SessionEventRow):
                self.db.execute(delete(table).where(table.session_id.in_(batch)))
            self.db.execute(delete(SessionRow).where(SessionRow.id.in_(batch)))
        values = [asdict(session) for session in sessions]
        links = [
            SessionEventRow(session_id=value["id"], event_id=event_id)
            for value in values
            for event_id in value.pop("event_ids")
        ]
        self.db.add_all(SessionRow(**value) for value in values)
        self.db.flush()
        self.db.add_all(links)
        self.db.add_all(DailyActivityRow(**asdict(record)) for record in daily)
        self.db.flush()
