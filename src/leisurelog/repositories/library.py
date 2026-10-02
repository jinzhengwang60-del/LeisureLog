"""Catalog persistence and SQL aggregation over existing daily/session facts."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, func, select, update

from leisurelog.domain.library import ContentIdentity
from leisurelog.repositories.models import (
    ContentAliasRow as Alias,
)
from leisurelog.repositories.models import (
    ContentItemRow as Item,
)
from leisurelog.repositories.models import (
    DailyActivityRow as Daily,
)
from leisurelog.repositories.models import (
    SessionRow as Session,
)

METRICS = (
    "active_seconds",
    "recorded_seconds",
    "afk_seconds",
    "unverified_seconds",
    "detected_afk_seconds",
    "retained_afk_seconds",
)
MATCH = and_(Alias.app == Daily.app, Alias.category == Daily.category, Alias.name == Daily.content)


def sums():
    return [func.sum(getattr(Daily, name)).label(name) for name in METRICS]


def item_values(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "name",
            "category",
            "notes",
            "created_at",
            "updated_at",
        )
    }


def alias_values(row):
    return {key: getattr(row, key) for key in ("id", "item_id", "app", "category", "name")}


class SQLiteLibrary:
    def __init__(self, db):
        self.db = db

    def register(self, values: list[ContentIdentity]):
        # Read metadata once. Reprocessing never overwrites the user's names or aliases.
        known = set(self.db.scalars(select(Alias.id)))
        for value in values:
            if value.id not in known:
                self._create_item(value.id, value.name.strip(), value.category)
                self.db.add(
                    Alias(
                        id=value.id,
                        item_id=value.id,
                        app=value.app,
                        category=value.category,
                        name=value.name,
                    )
                )
                known.add(value.id)
        self.db.flush()

    def _create_item(self, item_id, name, category):
        if self.db.get(Item, item_id) is None:
            now = datetime.now(timezone.utc)
            self.db.add(
                Item(
                    id=item_id,
                    name=name,
                    category=category,
                    notes="",
                    created_at=now,
                    updated_at=now,
                )
            )
            self.db.flush()

    def item(self, item_id):
        row = self.db.get(Item, item_id)
        if row is None:
            raise KeyError(item_id)
        return item_values(row)

    def alias(self, alias_id):
        row = self.db.get(Alias, alias_id)
        if row is None:
            raise KeyError(alias_id)
        return alias_values(row)

    def update_item(self, item_id, name, notes):
        self.db.execute(
            update(Item)
            .where(Item.id == item_id)
            .values(
                name=name,
                notes=notes,
                updated_at=datetime.now(timezone.utc),
            )
        )

    def add_alias(self, item_id, value):
        row = self.db.get(Alias, value.id)
        if row and row.item_id != item_id:
            raise ValueError("这个应用下的名称已归入其他作品，请通过合并来关联")
        if row is None:
            self.db.add(
                Alias(
                    id=value.id,
                    item_id=item_id,
                    app=value.app,
                    category=value.category,
                    name=value.name,
                )
            )
        self.db.flush()

    def merge(self, source_id, target_id):
        if not self.db.scalar(select(Alias.id).where(Alias.item_id == source_id).limit(1)):
            raise ValueError("这个内容已经合并到其他条目，请刷新")
        self.db.execute(update(Alias).where(Alias.item_id == source_id).values(item_id=target_id))
        self.db.execute(
            update(Item)
            .where(Item.id == target_id)
            .values(
                updated_at=datetime.now(timezone.utc),
            )
        )

    def split(self, alias_id):
        alias = self.db.get(Alias, alias_id)
        count = self.db.scalar(
            select(func.count()).select_from(Alias).where(Alias.item_id == alias.item_id)
        )
        if count < 2:
            raise ValueError("只有一个名称，无需拆分")
        # Restore an original, now empty item when possible, including its name and notes.
        original = self.db.get(Item, alias.id)
        original_in_use = self.db.scalar(select(Alias.id).where(Alias.item_id == alias.id).limit(1))
        new_id = alias.id if original is not None and not original_in_use else str(uuid4())
        self._create_item(new_id, alias.name.strip(), alias.category)
        alias.item_id = new_id
        self.db.flush()
        return new_id

    def _aggregate(self):
        return (
            select(
                Alias.item_id.label("id"),
                *sums(),
                func.count(func.distinct(Daily.day)).label("days"),
                func.count(func.distinct(Daily.session_id)).label("sessions"),
                func.min(Session.start_time).label("first_seen"),
                func.max(Session.end_time).label("last_seen"),
            )
            .select_from(Alias)
            .join(Daily, MATCH)
            .join(Session, Session.id == Daily.session_id)
            .group_by(Alias.item_id)
            .subquery()
        )

    def listing(self, query="", category="", sort="recent", limit=50, offset=0):
        aggregate = self._aggregate()
        filters = [select(Alias.id).where(Alias.item_id == Item.id).exists()]
        if category:
            filters.append(Item.category == category)
        if query:
            matching_alias = (
                select(Alias.id)
                .where(
                    Alias.item_id == Item.id,
                    func.lower(Alias.name).contains(query.lower(), autoescape=True),
                )
                .exists()
            )
            filters.append(
                func.lower(Item.name).contains(query.lower(), autoescape=True) | matching_alias
            )
        count = self.db.scalar(select(func.count()).select_from(Item).where(*filters))
        statement = (
            select(
                Item.id,
                Item.name,
                Item.category,
                Item.notes,
                *[
                    func.coalesce(aggregate.c[key], 0).label(key)
                    for key in (*METRICS, "days", "sessions")
                ],
                aggregate.c.first_seen,
                aggregate.c.last_seen,
            )
            .outerjoin(aggregate, aggregate.c.id == Item.id)
            .where(*filters)
        )
        ordering = (
            func.coalesce(aggregate.c.active_seconds, 0).desc()
            if sort == "time"
            else aggregate.c.last_seen.desc()
        )
        items = [
            dict(row)
            for row in self.db.execute(
                statement.order_by(ordering, Item.name, Item.id).limit(limit).offset(offset),
            ).mappings()
        ]
        # Fetch only this page's names to distinguish identical titles in different apps.
        page_ids = [item["id"] for item in items]
        app_groups = {item_id: set() for item_id in page_ids}
        alias_counts = dict.fromkeys(page_ids, 0)
        if page_ids:
            for item_id, app in self.db.execute(
                select(Alias.item_id, Alias.app).where(Alias.item_id.in_(page_ids))
            ):
                app_groups[item_id].add(app)
                alias_counts[item_id] += 1
        for item in items:
            item["apps"] = sorted(app_groups[item["id"]])
            item["alias_count"] = alias_counts[item["id"]]
        total_seconds = self.db.scalar(
            select(func.coalesce(func.sum(aggregate.c.active_seconds), 0))
            .select_from(Item)
            .outerjoin(aggregate, aggregate.c.id == Item.id)
            .where(*filters)
        )
        categories = list(
            self.db.scalars(
                select(Item.category)
                .where(
                    select(Alias.id).where(Alias.item_id == Item.id).exists(),
                )
                .distinct()
                .order_by(Item.category)
            )
        )
        return {
            "items": items,
            "total": count,
            "active_seconds": total_seconds,
            "limit": limit,
            "offset": offset,
            "categories": categories,
        }

    def detail(self, item_id, limit=30, offset=0):
        item = self.item(item_id)
        aggregate = self._aggregate()
        summary = (
            self.db.execute(select(aggregate).where(aggregate.c.id == item_id)).mappings().first()
        )
        item.update(
            dict(summary)
            if summary
            else {
                **{key: 0 for key in (*METRICS, "days", "sessions")},
                "first_seen": None,
                "last_seen": None,
            }
        )
        aliases = [
            alias_values(row)
            for row in self.db.scalars(
                select(Alias)
                .where(Alias.item_id == item_id)
                .order_by(Alias.app, Alias.name, Alias.id)
            )
        ]
        facts = (
            select(Daily.day.label("day"), *sums())
            .select_from(Daily)
            .join(Alias, MATCH)
            .where(Alias.item_id == item_id)
            .group_by(Daily.day)
            .subquery()
        )
        days = [
            dict(row)
            for row in self.db.execute(
                select(facts).order_by(facts.c.day.desc()).limit(limit).offset(offset)
            ).mappings()
        ]
        period = func.strftime("%Y-%m", Daily.day)
        months = [
            dict(row)
            for row in self.db.execute(
                select(
                    period.label("month"),
                    *sums(),
                    func.count(func.distinct(Daily.day)).label("days"),
                )
                .select_from(Daily)
                .join(Alias, MATCH)
                .where(Alias.item_id == item_id)
                .group_by(period)
                .order_by(period),
            ).mappings()
        ]
        recent = [
            dict(row)
            for row in self.db.execute(
                select(
                    Session.id,
                    Session.app,
                    Session.title,
                    Session.url,
                    Session.classification,
                    Session.start_time,
                    Session.end_time,
                    Session.active_seconds,
                    Session.recorded_seconds,
                    func.min(Daily.day).label("day"),
                )
                .select_from(Session)
                .join(Daily, Daily.session_id == Session.id)
                .join(Alias, MATCH)
                .where(Alias.item_id == item_id)
                .group_by(Session.id)
                .order_by(Session.start_time.desc(), Session.id)
                .limit(20)
            ).mappings()
        ]
        return {
            "item": item,
            "aliases": aliases,
            "months": months,
            "days": days,
            "day_total": item["days"],
            "limit": limit,
            "offset": offset,
            "recent_sessions": recent,
        }
