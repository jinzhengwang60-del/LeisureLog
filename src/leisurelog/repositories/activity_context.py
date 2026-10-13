"""Persistent project metadata, independent context decisions and bounded SQL reports."""

from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select

from leisurelog.domain.activity_context import ContextRule
from leisurelog.repositories.models import (
    ActivityProjectRow,
    ContextChangeRow,
    ContextOverrideRow,
    ContextRuleRow,
    DailyActivityRow,
    ResolvedEventRow,
    SessionEventRow,
    SessionRow,
)


def project_value(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "name",
            "description",
            "color",
            "archived",
            "created_at",
            "updated_at",
            "goal_seconds",
        )
    }


class SQLiteContext:
    def __init__(self, db):
        self.db = db

    def projects(self):
        return [
            project_value(row)
            for row in self.db.scalars(
                select(ActivityProjectRow).order_by(
                    ActivityProjectRow.archived, ActivityProjectRow.name, ActivityProjectRow.id
                )
            )
        ]

    def project(self, project_id):
        row = self.db.get(ActivityProjectRow, project_id)
        if row is None:
            raise KeyError(project_id)
        return project_value(row)

    def save_project(self, project_id, values):
        now = datetime.now(timezone.utc)
        row = self.db.get(ActivityProjectRow, project_id) if project_id else None
        if project_id and row is None:
            raise KeyError(project_id)
        if row is None:
            row = ActivityProjectRow(id=str(uuid4()), created_at=now)
            self.db.add(row)
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = now
        self.db.flush()
        return project_value(row)

    def context_overrides(self, scope=None):
        query = select(ContextOverrideRow)
        if scope is not None:
            query = query.where(ContextOverrideRow.window_event_id.in_(scope))
        return {row.event_id: row.assignments for row in self.db.scalars(query)}

    def context_rules(self):
        return [
            ContextRule(**{key: getattr(row, key) for key in ContextRule.__dataclass_fields__})
            for row in self.db.scalars(
                select(ContextRuleRow).order_by(ContextRuleRow.updated_at.desc(), ContextRuleRow.id)
            )
        ]

    def save_context(self, event, values):
        row = self.db.get(ContextOverrideRow, event.id)
        if values is None:
            inherited = self.db.get(ContextOverrideRow, event.window_event_id)
            if event.id != event.window_event_id and inherited is not None:
                values = {"purpose": None, "project_id": "__auto__"}
            elif row is not None:
                self.db.delete(row)
        if values is not None:
            if row is None:
                row = ContextOverrideRow(
                    event_id=event.id, window_event_id=event.window_event_id, assignments={}
                )
                self.db.add(row)
            row.assignments = {**row.assignments, **values}
        self.db.flush()

    def save_context_rule(self, rule):
        row = self.db.get(ContextRuleRow, rule.id)
        if row is None:
            row = ContextRuleRow(
                **{key: getattr(rule, key) for key in ("id", "source", "app", "scope", "value")},
                assignments={},
            )
            self.db.add(row)
        row.assignments = {**row.assignments, **rule.assignments}
        row.updated_at = datetime.now(timezone.utc)
        self.db.flush()

    def delete_context_rule(self, rule_id):
        if self.db.get(ContextRuleRow, rule_id) is None:
            raise KeyError(rule_id)
        self.db.execute(delete(ContextRuleRow).where(ContextRuleRow.id == rule_id))
        self.db.flush()

    def decision_snapshot(self, event_ids, rule_id=None):
        rows = {
            row.event_id: {"window_event_id": row.window_event_id, "assignments": row.assignments}
            for row in self.db.scalars(
                select(ContextOverrideRow).where(ContextOverrideRow.event_id.in_(event_ids))
            )
        }
        snapshot = {"overrides": {event_id: rows.get(event_id) for event_id in event_ids}}
        if rule_id is not None:
            row = self.db.get(ContextRuleRow, rule_id)
            snapshot["rules"] = {
                rule_id: {
                    **{key: getattr(row, key) for key in ContextRule.__dataclass_fields__},
                    "updated_at": row.updated_at.isoformat(),
                }
                if row
                else None
            }
        return snapshot

    def restore_decisions(self, snapshot):
        for event_id, value in snapshot["overrides"].items():
            row = self.db.get(ContextOverrideRow, event_id)
            if value is None:
                if row is not None:
                    self.db.delete(row)
            elif row is None:
                self.db.add(ContextOverrideRow(event_id=event_id, **value))
            else:
                row.window_event_id, row.assignments = (
                    value["window_event_id"],
                    value["assignments"],
                )
        for rule_id, value in snapshot.get("rules", {}).items():
            row = self.db.get(ContextRuleRow, rule_id)
            if value is None:
                if row is not None:
                    self.db.delete(row)
            else:
                if row is None:
                    row = ContextRuleRow(id=rule_id)
                    self.db.add(row)
                for key, item in value.items():
                    setattr(row, key, datetime.fromisoformat(item) if key == "updated_at" else item)
        self.db.flush()

    def save_change(self, action, before, after):
        if before == after:
            return None
        row = ContextChangeRow(
            id=str(uuid4()),
            action=action,
            event_count=len(after["overrides"]),
            before=before,
            after=after,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(row)
        self.db.flush()
        return row.id

    def change(self, change_id):
        row = self.db.get(ContextChangeRow, change_id)
        if row is None:
            raise KeyError(change_id)
        return {key: getattr(row, key) for key in ContextChangeRow.__annotations__}

    def changes(self, limit, offset):
        rows = self.db.scalars(
            select(ContextChangeRow)
            .order_by(ContextChangeRow.created_at.desc(), ContextChangeRow.id)
            .limit(limit)
            .offset(offset)
        )
        return {
            "total": self.db.scalar(select(func.count()).select_from(ContextChangeRow)),
            "items": [
                {
                    key: getattr(row, key)
                    for key in ("id", "action", "event_count", "created_at", "undone_at")
                }
                for row in rows
            ],
        }

    def mark_undone(self, change_id):
        self.db.get(ContextChangeRow, change_id).undone_at = datetime.now(timezone.utc)
        self.db.flush()

    def project_lifetime_seconds(self):
        row = DailyActivityRow
        return dict(
            self.db.execute(
                select(row.project_id, func.sum(row.active_seconds))
                .where(row.project_id.is_not(None))
                .group_by(row.project_id)
            ).all()
        )

    def project_facts(self, start, end, project_id=None):
        row = DailyActivityRow
        condition = [row.day >= start, row.day <= end]
        if project_id is not None:
            condition.append(row.project_id == project_id)
        measures = [
            func.sum(row.active_seconds).label("active_seconds"),
            func.sum(row.recorded_seconds).label("recorded_seconds"),
            func.sum(row.unverified_seconds).label("unverified_seconds"),
            func.count(func.distinct(row.day)).label("days"),
            func.count(func.distinct(row.session_id)).label("sessions"),
        ]

        def grouped(*columns, limit=None):
            query = (
                select(*columns, *measures)
                .where(*condition)
                .group_by(*columns)
                .order_by(func.sum(row.active_seconds).desc(), *columns)
            )
            if limit is not None:
                query = query.limit(limit)
            return [dict(r) for r in self.db.execute(query).mappings()]

        return {
            "projects": grouped(row.project_id),
            "apps": grouped(row.app, limit=20),
            "purposes": grouped(row.purpose),
            "days": grouped(row.day),
        }

    def week_facts(self, start, end):
        row = DailyActivityRow
        condition = [row.day >= start, row.day <= end]
        measures = [
            func.sum(row.active_seconds).label("active_seconds"),
            func.count(func.distinct(row.day)).label("days"),
        ]

        def grouped(*columns):
            return [
                dict(r)
                for r in self.db.execute(
                    select(*columns, *measures).where(*condition).group_by(*columns)
                ).mappings()
            ]

        return {
            "days": grouped(row.day, row.purpose),
            "activities": grouped(row.app, row.category, row.content, row.purpose, row.project_id),
            "projects": grouped(row.project_id),
        }

    def pending_facts(self, start, end, limit, offset, search):
        day, session = DailyActivityRow, SessionRow
        app = func.leisurelog_casefold(session.app)
        website = func.leisurelog_hostname(session.url)
        conditions = [
            day.day >= start,
            day.day <= end,
            day.purpose == "unknown",
            day.active_seconds > 0,
        ]
        if search:
            conditions.append(
                app.contains(search.casefold(), autoescape=True)
                | website.contains(search.casefold(), autoescape=True)
            )
        grouped = (
            select(
                session.source.label("source"),
                app.label("app"),
                website.label("website"),
                func.min(session.app).label("app_name"),
                func.sum(day.active_seconds).label("active_seconds"),
                func.count(func.distinct(day.session_id)).label("sessions"),
                func.count(func.distinct(day.day)).label("days"),
                func.max(session.end_time).label("last_seen"),
                func.min(session.title).label("sample_title"),
            )
            .join(session, day.session_id == session.id)
            .where(*conditions)
            .group_by(session.source, app, website)
        )
        facts = grouped.subquery()
        groups, seconds = self.db.execute(
            select(func.count(), func.coalesce(func.sum(facts.c.active_seconds), 0))
        ).one()
        rows = self.db.execute(
            select(facts)
            .order_by(facts.c.active_seconds.desc(), facts.c.source, facts.c.app, facts.c.website)
            .limit(limit)
            .offset(offset)
        ).mappings()
        return {"groups": groups, "active_seconds": seconds, "items": [dict(row) for row in rows]}

    def pending_events(self, start, end, source, app, website, limit, offset):
        row, session, day = ResolvedEventRow, SessionRow, DailyActivityRow
        zone = timezone(timedelta(hours=8))
        begin = datetime.combine(start, time.min, zone)
        finish = datetime.combine(end + timedelta(days=1), time.min, zone)
        statement = (
            select(row.id)
            .join(SessionEventRow, row.id == SessionEventRow.event_id)
            .join(session, SessionEventRow.session_id == session.id)
            .join(day, day.session_id == session.id)
            .where(
                day.day >= start,
                day.day <= end,
                day.purpose == "unknown",
                day.active_seconds > 0,
                row.end_time > begin,
                row.start_time < finish,
                session.source == source,
                func.leisurelog_casefold(session.app) == app.casefold(),
                func.leisurelog_hostname(session.url) == website.casefold(),
            )
            .distinct()
        )
        total = self.db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = self.db.scalars(
            select(row)
            .where(row.id.in_(statement))
            .order_by(row.end_time.desc(), row.id)
            .limit(limit)
            .offset(offset)
        )
        return {
            "total_events": total,
            "items": [
                {
                    key: getattr(value, key)
                    for key in ("id", "app", "title", "url", "start_time", "end_time", "context")
                }
                for value in rows
            ],
        }
