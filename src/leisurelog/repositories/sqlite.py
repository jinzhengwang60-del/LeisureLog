import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session as DBSession

from leisurelog.domain.activity_context import ActivityContext
from leisurelog.domain.browser import BrowserEvent, BrowserSourceRecord, ResolvedActivity
from leisurelog.domain.learned_rules import LearnedRule
from leisurelog.domain.models import (
    ActivityEvent,
    Classification,
    IdleEvent,
    IdleSourceRecord,
    Session,
    SourceRecord,
)
from leisurelog.domain.processing import ProcessingRange
from leisurelog.repositories.activity_context import SQLiteContext
from leisurelog.repositories.context_processing import SQLiteContextProcessing
from leisurelog.repositories.library import SQLiteLibrary
from leisurelog.repositories.models import (
    ActivityEventRow,
    BrowserEventRow,
    DailyActivityRow,
    IdleEventRow,
    LearnedRuleRow,
    ManualOverrideRow,
    RawEventRow,
    ResolvedEventRow,
    SegmentOverrideRow,
    SessionEventRow,
    SessionRow,
    TimingOverrideRow,
)
from leisurelog.repositories.processing_scope import condition, plan, query


def classification(value: dict) -> Classification:
    return Classification(**{**value, "tags": tuple(value.get("tags", []))})


def resolved_value(row):
    return ResolvedActivity(
        **{
            key: classification(row.classification)
            if key == "classification"
            else ActivityContext(**(row.context or {}))
            if key == "context"
            else getattr(row, key)
            for key in ResolvedActivity.__dataclass_fields__
        }
    )


class SQLiteRepository:
    def __init__(self, db: DBSession):
        self.db = db
        self._changes = []

    def mark_changed(self, event, *, window=True):
        self._changes.append(
            ProcessingRange(
                event.source,
                event.device,
                event.stream if window else None,
                event.start_time,
                event.end_time,
            )
        )

    def processing_scope(self, gap_seconds):
        return plan(self.db, self._changes, gap_seconds)

    def context_overrides(self, scope=None, *, window_ids=None):
        return SQLiteContext(self.db).context_overrides(
            window_ids
            if window_ids is not None
            else self.window_ids(scope)
            if scope is not None
            else None
        )

    def context_rules(self):
        return SQLiteContext(self.db).context_rules()

    def projects(self):
        return SQLiteContext(self.db).projects()

    def context_events(self, window_ids):
        return [resolved_value(row) for row in SQLiteContextProcessing(self.db).events(window_ids)]

    def save_contexts(self, events):
        SQLiteContextProcessing(self.db).save_contexts(events)

    def context_batches(self, event_ids):
        store = SQLiteContextProcessing(self.db)
        batches = [(ids, []) for ids in store.session_groups(event_ids)]
        by_session = {key: values for ids, values in batches for key in ids}
        for session_id, row in store.session_events(by_session):
            by_session[session_id].append(resolved_value(row))
        return batches

    def replace_context_sessions(self, sessions, old_ids, daily):
        SQLiteContextProcessing(self.db).replace_sessions(sessions, old_ids, daily)

    def clear_changes(self):
        self._changes.clear()

    def counts(self):
        return {
            "events": self.db.scalar(select(func.count()).select_from(ActivityEventRow)),
            "sessions": self.db.scalar(select(func.count()).select_from(SessionRow)),
        }

    def summary_totals(self):
        row = SessionRow
        category = row.classification["category"].as_string()
        grouped = self.db.execute(
            select(category, func.sum(row.recorded_seconds), func.sum(row.active_seconds)).group_by(
                category
            )
        ).all()
        fields = [
            "afk_seconds",
            "detected_afk_seconds",
            "retained_afk_seconds",
            "unverified_seconds",
        ]
        totals = self.db.execute(
            select(
                func.count(row.id), *[func.coalesce(func.sum(getattr(row, k)), 0) for k in fields]
            )
        ).one()
        return {
            "session_count": totals[0],
            "recorded_seconds_by_category": {r[0]: r[1] for r in grouped},
            "active_seconds_by_category": {r[0]: r[2] for r in grouped},
            **dict(zip(fields, totals[1:], strict=True)),
            "scope": (
                "configured timing policy applied; detected AFK preserved; no cross-stream dedup"
            ),
        }

    def browser_facts(self):
        row = BrowserEventRow
        grouped = self.db.execute(
            select(row.stream, row.device, func.count(row.id), func.max(row.end_time)).group_by(
                row.stream, row.device
            )
        ).all()
        buckets = {}
        for stream, device, count, last in grouped:
            item = buckets.setdefault(stream, {"devices": [], "records": 0, "last_record_at": last})
            item["devices"].append(device)
            item["records"] += count
            item["last_record_at"] = max(item["last_record_at"], last)
        return {
            "streams": buckets,
            "browser_records": sum(r[2] for r in grouped),
            "matched_segments": self.db.scalar(
                select(func.count())
                .select_from(ResolvedEventRow)
                .where(ResolvedEventRow.browser_event_id.is_not(None))
            ),
        }

    def window_ids(self, scope):
        return select(ActivityEventRow.id).where(condition(ActivityEventRow, scope))

    def register_content(self, values):
        SQLiteLibrary(self.db).register(values)

    def learned_rules(self) -> list[LearnedRule]:
        return [
            LearnedRule(r.id, r.source, r.app, r.scope, r.value, classification(r.classification))
            for r in self.db.scalars(
                select(LearnedRuleRow).order_by(LearnedRuleRow.updated_at.desc(), LearnedRuleRow.id)
            )
        ]

    def unclassified_apps(self, limit: int = 200) -> list[dict]:
        """Unknown-category time grouped by source and app, largest first (SQL aggregate)."""
        row = SessionRow
        unknown = row.classification["category"].as_string() == "unknown"
        active = func.sum(row.active_seconds)
        groups = self.db.execute(
            select(
                row.source,
                row.app,
                active,
                func.sum(row.recorded_seconds),
                func.count(row.id),
                func.max(row.end_time),
                func.sum(case((row.url.is_not(None), 1), else_=0)),
            )
            .where(unknown)
            .group_by(row.source, row.app)
            .order_by(active.desc(), row.app)
            .limit(limit)
        ).all()
        result = []
        for source, app, active_seconds, recorded, count, last, with_url in groups:
            title_time = func.sum(row.active_seconds)
            titles = self.db.execute(
                select(row.title)
                .where(unknown, row.source == source, row.app == app, row.title != "")
                .group_by(row.title)
                .order_by(title_time.desc(), row.title)
                .limit(3)
            ).scalars()
            result.append(
                {
                    "source": source,
                    "app": app,
                    "active_seconds": active_seconds or 0,
                    "recorded_seconds": recorded or 0,
                    "session_count": count,
                    "last_seen": last,
                    "sessions_with_url": with_url or 0,
                    "sample_titles": list(titles),
                }
            )
        return result

    def app_event(self, source: str, app: str):
        found = self.db.scalars(
            select(ResolvedEventRow.id)
            .where(ResolvedEventRow.source == source, ResolvedEventRow.app == app)
            .limit(1)
        ).first()
        return self.resolved_events(ids=[found])[0] if found else None

    def save_rule(self, rule: LearnedRule) -> None:
        values = asdict(rule)
        values["updated_at"] = datetime.now(timezone.utc)
        row = self.db.get(LearnedRuleRow, rule.id)
        if row is None:
            self.db.add(LearnedRuleRow(**values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self.db.flush()

    def delete_rule(self, rule_id: str) -> None:
        row = self.db.get(LearnedRuleRow, rule_id)
        if row is None:
            raise KeyError(rule_id)
        self.db.delete(row)
        self.db.flush()

    def ingest(self, record: SourceRecord | IdleSourceRecord | BrowserSourceRecord) -> bool:
        event = record.event
        row_type = (
            BrowserEventRow
            if isinstance(event, BrowserEvent)
            else IdleEventRow
            if isinstance(event, IdleEvent)
            else ActivityEventRow
        )
        row = self.db.get(row_type, event.id)
        crop_start, crop_end = getattr(record, "cropped", (False, False))
        if row:
            previous = self.db.get(RawEventRow, row.raw_event_id)
            # ActivityWatch crops events to the requested range, so an event running across
            # several sync windows arrives as a different slice each time. On an edge the source
            # cut, keep what was already stored; uncut edges are the source's truth.
            if crop_start or crop_end:
                event = replace(
                    event,
                    start_time=min(row.start_time, event.start_time)
                    if crop_start
                    else event.start_time,
                    end_time=max(row.end_time, event.end_time) if crop_end else event.end_time,
                )
            unchanged = all(
                (tuple(getattr(row, key)) if key == "browser_apps" else getattr(row, key))
                == getattr(event, key)
                for key in event.__dataclass_fields__
                if key != "classification"
            )
            # Bucket last_updated changes every heartbeat and is not an event revision;
            # a cropped slice that lies inside what is stored adds nothing either.
            if unchanged and (crop_start or crop_end or previous.payload == record.payload):
                return False
        digest = hashlib.sha256(
            json.dumps(
                [record.payload, record.metadata],
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        raw = self.db.scalar(
            select(RawEventRow).where(
                RawEventRow.event_id == event.id,
                RawEventRow.payload_hash == digest,
            )
        )
        if raw and row and row.raw_event_id == raw.id:
            return False
        if raw is None:
            raw = RawEventRow(
                event_id=event.id,
                source=event.source,
                stream=event.stream,
                source_event_id=record.source_event_id,
                payload_hash=digest,
                payload=record.payload,
                source_metadata=record.metadata,
            )
            self.db.add(raw)
            self.db.flush()
        if row is not None:
            self.mark_changed(row, window=row_type is ActivityEventRow)
        self.mark_changed(event, window=row_type is ActivityEventRow)
        values = asdict(event)
        if row is None:
            row = row_type(**values, raw_event_id=raw.id)
            self.db.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.raw_event_id = raw.id
        self.db.flush()
        return True

    def idle_events(self, **filters) -> list[IdleEvent]:
        return [
            IdleEvent(**{key: getattr(row, key) for key in IdleEvent.__dataclass_fields__})
            for row in self.db.scalars(query(IdleEventRow, streams=False, **filters))
        ]

    def events(self, **filters) -> list[ActivityEvent]:
        rows = self.db.scalars(query(ActivityEventRow, **filters))
        return [
            ActivityEvent(
                **{
                    key: getattr(row, key)
                    for key in ActivityEvent.__dataclass_fields__
                    if key != "classification"
                },
                classification=classification(row.classification),
            )
            for row in rows
        ]

    def browser_events(self, **filters):
        return [
            BrowserEvent(
                **{
                    key: (tuple(row.browser_apps) if key == "browser_apps" else getattr(row, key))
                    for key in BrowserEvent.__dataclass_fields__
                }
            )
            for row in self.db.scalars(query(BrowserEventRow, streams=False, **filters))
        ]

    def resolved_events(self, **filters):
        return [resolved_value(row) for row in self.db.scalars(query(ResolvedEventRow, **filters))]

    def context_candidates(self, rule):
        row = ResolvedEventRow
        conditions = [row.source == rule.source, func.leisurelog_casefold(row.app) == rule.app]
        if rule.scope == "title":
            conditions.append(row.title == rule.value)
        elif rule.scope == "title_contains":
            conditions.append(
                func.leisurelog_casefold(row.title).contains(rule.value, autoescape=True)
            )
        elif rule.scope in {"domain", "url"}:
            value = (
                func.leisurelog_hostname(row.url)
                if rule.scope == "domain"
                else func.leisurelog_url(row.url)
            )
            conditions.append(value == rule.value)
        statement = select(row).where(*conditions).order_by(row.id).execution_options(yield_per=256)
        return (resolved_value(value) for value in self.db.scalars(statement))

    def save_resolved(self, events):
        for event in events:
            row = self.db.get(ResolvedEventRow, event.id)
            values = asdict(event)
            if row is None:
                self.db.add(ResolvedEventRow(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        self.db.flush()

    def prune_resolved(self, scope=None):
        # Session links are the current derived set; avoid SQLite parameter limits.
        statement = delete(ResolvedEventRow).where(
            ~ResolvedEventRow.id.in_(select(SessionEventRow.event_id))
        )
        if scope is not None:
            statement = statement.where(
                ResolvedEventRow.window_event_id.in_(self.window_ids(scope))
            )
        self.db.execute(statement.execution_options(synchronize_session=False))
        self.db.flush()

    def timing_overrides(self, scope=None):
        statement = select(TimingOverrideRow)
        if scope is not None:
            statement = statement.where(
                TimingOverrideRow.window_event_id.in_(self.window_ids(scope))
            )
        return {r.event_id: r.policy for r in self.db.scalars(statement)}

    def set_timing_override(self, event_id, policy):
        event = self.db.get(ResolvedEventRow, event_id)
        if event is None:
            raise KeyError(event_id)
        self.mark_changed(self.db.get(ActivityEventRow, event.window_event_id))
        row = self.db.get(TimingOverrideRow, event_id)
        inherited = (
            self.db.get(TimingOverrideRow, event.window_event_id)
            if event_id != event.window_event_id
            else None
        )
        if policy is None and inherited is not None:
            policy = "default"
        if policy is None:
            if row:
                self.db.delete(row)
        elif row:
            row.policy = policy
        else:
            self.db.add(
                TimingOverrideRow(
                    event_id=event_id, window_event_id=event.window_event_id, policy=policy
                )
            )
        self.db.flush()

    def overrides(self, scope=None) -> dict[str, Classification | None]:
        result = {}
        for table in (ManualOverrideRow, SegmentOverrideRow):
            statement = select(table)
            if scope is not None:
                anchor = table.event_id if table is ManualOverrideRow else table.window_event_id
                statement = statement.where(anchor.in_(self.window_ids(scope)))
            for row in self.db.scalars(statement):
                result[row.event_id] = (
                    classification(row.classification) if row.classification is not None else None
                )
        return result

    def set_override(self, event_id: str, value: Classification | None) -> None:
        original = self.db.get(ActivityEventRow, event_id)
        resolved = self.db.get(ResolvedEventRow, event_id)
        if original is None and resolved is None:
            raise KeyError(event_id)
        self.mark_changed(original or self.db.get(ActivityEventRow, resolved.window_event_id))
        table = ManualOverrideRow if original else SegmentOverrideRow
        row = self.db.get(table, event_id)
        if value is None:
            inherited = (
                None if original else self.db.get(ManualOverrideRow, resolved.window_event_id)
            )
            if inherited is not None:
                # A segment reset suppresses the inherited window override.
                if row:
                    row.classification = None
                else:
                    self.db.add(
                        SegmentOverrideRow(
                            event_id=event_id,
                            window_event_id=resolved.window_event_id,
                            classification=None,
                        )
                    )
            elif row:
                self.db.delete(row)
        elif row:
            row.classification = asdict(value)
        else:
            self.db.add(
                table(
                    event_id=event_id,
                    classification=asdict(value),
                    **({"window_event_id": resolved.window_event_id} if not original else {}),
                )
            )
        self.db.flush()

    def save_classification(self, event: ActivityEvent) -> None:
        self.db.get(ActivityEventRow, event.id).classification = asdict(event.classification)

    def replace_sessions(self, sessions: list[Session], scope=None) -> None:
        affected = select(SessionRow.id)
        if scope is not None:
            affected = affected.where(condition(SessionRow, scope))
        for table in (DailyActivityRow, SessionEventRow):
            self.db.execute(
                delete(table)
                .where(table.session_id.in_(affected))
                .execution_options(synchronize_session=False)
            )
        statement = delete(SessionRow)
        if scope is not None:
            statement = statement.where(condition(SessionRow, scope))
        self.db.execute(statement.execution_options(synchronize_session=False))
        for session in sessions:
            values = asdict(session)
            event_ids = values.pop("event_ids")
            self.db.add(SessionRow(**values))
            self.db.flush()
            self.db.add_all(
                [
                    SessionEventRow(session_id=session.id, event_id=event_id)
                    for event_id in event_ids
                ]
            )
        self.db.flush()

    def sessions(self, **filters) -> list[Session]:
        statement = query(SessionRow, **filters)
        selected = statement.with_only_columns(SessionRow.id).subquery()
        links = {}
        for link in self.db.scalars(
            select(SessionEventRow).where(SessionEventRow.session_id.in_(select(selected.c.id)))
        ):
            links.setdefault(link.session_id, []).append(link.event_id)
        return [
            Session(
                **{
                    key: getattr(row, key)
                    for key in Session.__dataclass_fields__
                    if key not in {"classification", "event_ids", "context"}
                },
                classification=classification(row.classification),
                event_ids=sorted(links.get(row.id, [])),
                context=ActivityContext(**(row.context or {})),
            )
            for row in self.db.scalars(statement)
        ]

    def replace_daily(self, records, scope=None):
        if scope is None:
            self.db.execute(delete(DailyActivityRow))
        self.db.add_all(DailyActivityRow(**asdict(record)) for record in records)
        self.db.flush()

    def range_statistics(self, start, end, granularity, purpose="", project_id=""):
        row = DailyActivityRow
        condition = [row.day >= start, row.day <= end]
        if purpose:
            condition.append(row.purpose == purpose)
        if project_id:
            condition.append(
                row.project_id.is_(None) if project_id == "none" else row.project_id == project_id
            )
        sums = [
            func.sum(getattr(row, key)).label(key)
            for key in [
                "recorded_seconds",
                "active_seconds",
                "afk_seconds",
                "unverified_seconds",
                "detected_afk_seconds",
                "retained_afk_seconds",
            ]
        ]

        def grouped(columns, limit=None):
            query = select(*columns, *sums).where(*condition).group_by(*columns)
            query = query.order_by(func.sum(row.active_seconds).desc(), *columns)
            if limit:
                query = query.limit(limit)
            return [dict(value) for value in self.db.execute(query).mappings()]

        bucket = func.strftime("%Y-%m" if granularity == "month" else "%Y-%m-%d", row.day).label(
            "period"
        )
        totals = dict(self.db.execute(select(*sums).where(*condition)).mappings().one())
        coverage = dict(
            self.db.execute(
                select(
                    func.min(row.day).label("first_day"),
                    func.max(row.day).label("last_day"),
                    func.count(func.distinct(row.day)).label("days_with_records"),
                    func.count(func.distinct(row.session_id)).label("session_count"),
                ).where(*condition)
            )
            .mappings()
            .one()
        )
        return {
            "totals": {k: v or 0 for k, v in totals.items()},
            "coverage": coverage,
            "categories": grouped([row.category]),
            "purposes": grouped([row.purpose]),
            "projects": grouped([row.project_id]),
            "apps": grouped([row.app], 20),
            "contents": [
                dict(value)
                for value in self.db.execute(
                    select(row.app, row.content, *sums)
                    .where(*condition, row.content.is_not(None), row.content != "")
                    .group_by(row.app, row.content)
                    .order_by(func.sum(row.active_seconds).desc(), row.app, row.content)
                    .limit(20)
                ).mappings()
            ],
            "trend": grouped([bucket]),
        }
