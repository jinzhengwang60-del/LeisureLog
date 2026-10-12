"""Persistent project metadata, independent context decisions and bounded SQL reports."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select

from leisurelog.domain.activity_context import ContextRule
from leisurelog.repositories.models import (
    ActivityProjectRow,
    ContextOverrideRow,
    ContextRuleRow,
    DailyActivityRow,
)


def project_value(row):
    return {
        key: getattr(row, key)
        for key in ("id", "name", "description", "color", "archived", "created_at", "updated_at")
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
