"""Read game totals from daily facts; never synthesize playtime from a catalog."""

import json

from sqlalchemy import case, func, select

from leisurelog.domain.game_types import resolve_game_type
from leisurelog.repositories.library import METRICS
from leisurelog.repositories.models import DailyActivityRow as Daily
from leisurelog.repositories.models import GameCatalogRow as Game
from leisurelog.repositories.models import GameTypeOverrideRow
from leisurelog.repositories.models import SessionRow as Session


class SQLiteGameStatistics:
    def __init__(self, db):
        self.db = db

    def _facts(self):
        # Stable SDK IDs survive catalog renames. Other classifiers can link by
        # an exact, unique current catalog name; ambiguous names stay separate.
        names = (
            select(Game.name, func.min(Game.id).label("id"), func.count().label("count"))
            .group_by(Game.name)
            .subquery()
        )
        origin = Session.classification["origin"].as_string()
        key = case(
            (origin.startswith("playnite:", autoescape=True), origin),
            (names.c.count == 1, "playnite:" + names.c.id),
            else_="named:" + func.json_array(Daily.app, Daily.content),
        )
        return (
            select(
                key.label("key"),
                Daily.day,
                Daily.session_id,
                Daily.content,
                Session.classification["tags"].label("source_tags"),
                Session.start_time,
                Session.end_time,
                *[getattr(Daily, metric) for metric in METRICS],
            )
            .join(Session, Daily.session_id == Session.id)
            .outerjoin(
                names,
                Daily.content == names.c.name,
            )
            .where(Daily.category == "game", Daily.content.is_not(None), Daily.content != "")
            .cte("game_facts")
        )

    def _entries(self):
        entries = {}
        for game in self.db.scalars(select(Game)):
            key = "playnite:" + game.id
            entries[key] = {
                "key": key,
                "name": game.name,
                "installed": game.installed,
                "in_catalog": True,
                "matches": game.matches,
                "tags": game.tags,
                **dict.fromkeys((*METRICS, "days", "sessions"), 0),
                "first_seen": None,
                "last_seen": None,
            }
        facts = self._facts()
        rows = self.db.execute(
            select(
                facts.c.key,
                func.max(facts.c.content).label("recorded_name"),
                *[func.sum(facts.c[m]).label(m) for m in METRICS],
                func.count(func.distinct(facts.c.day)).label("days"),
                func.count(func.distinct(facts.c.session_id)).label("sessions"),
                func.min(facts.c.start_time).label("first_seen"),
                func.max(facts.c.end_time).label("last_seen"),
            ).group_by(facts.c.key)
        ).mappings()
        for row in rows:
            stats = dict(row)
            key = stats.pop("key")
            recorded_name = stats.pop("recorded_name")
            if key not in entries:
                entries[key] = {
                    "key": key,
                    "name": recorded_name,
                    "installed": None,
                    "in_catalog": False,
                    "matches": [],
                    "tags": [],
                }
            entries[key].update(stats)
            entries[key]["app"] = json.loads(key[6:])[0] if key.startswith("named:") else None
        observed_tags = {}
        for key, tags in self.db.execute(select(facts.c.key, facts.c.source_tags).distinct()):
            observed_tags.setdefault(key, []).extend(tags or [])
        overrides = {
            row.game_key: {"primary": row.primary_type, "tags": row.tags}
            for row in self.db.scalars(select(GameTypeOverrideRow))
        }
        for key, item in entries.items():
            # Current source catalog is authoritative for automatic suggestions.
            # Historical classification tags are a fallback when it has no tags.
            source_tags = item["tags"] or observed_tags.get(key, [])
            item["game_type"] = resolve_game_type(source_tags, overrides.get(key))
        return entries

    def listing(self, query="", scope="tracked", sort="time", limit=50, offset=0):
        items = [
            item for item in self._entries().values() if query.casefold() in item["name"].casefold()
        ]
        if scope == "tracked":
            items = [i for i in items if i["sessions"] or (i["installed"] and i["matches"])]
        elif scope == "recorded":
            items = [i for i in items if i["sessions"]]
        items.sort(key=lambda i: (i["name"].casefold(), i["key"]))
        items.sort(
            key=lambda i: (
                (i["last_seen"].isoformat() if i["last_seen"] else "")
                if sort == "recent"
                else i["active_seconds"]
            ),
            reverse=True,
        )
        return {
            "items": items[offset : offset + limit],
            "total": len(items),
            "recorded_games": sum(bool(i["sessions"]) for i in items),
            "active_seconds": sum(i["active_seconds"] for i in items),
            "limit": limit,
            "offset": offset,
        }

    def detail(self, key, limit=30, offset=0):
        item = self._entries().get(key)
        if item is None:
            raise KeyError(key)
        facts = self._facts()
        metrics = [func.sum(facts.c[m]).label(m) for m in METRICS]
        days = [
            dict(row)
            for row in self.db.execute(
                select(facts.c.day, *metrics)
                .where(facts.c.key == key)
                .group_by(facts.c.day)
                .order_by(facts.c.day.desc())
                .limit(limit)
                .offset(offset),
            ).mappings()
        ]
        period = func.strftime("%Y-%m", facts.c.day)
        months = [
            dict(row)
            for row in self.db.execute(
                select(period.label("month"), *metrics)
                .where(facts.c.key == key)
                .group_by(period)
                .order_by(period),
            ).mappings()
        ]
        # A cross-midnight session is one recent fragment, while daily totals
        # already have the correct Beijing-day allocation and AFK deductions.
        recent = [
            dict(row)
            for row in self.db.execute(
                select(
                    Session.id,
                    Session.app,
                    Session.title,
                    Session.classification,
                    Session.start_time,
                    Session.end_time,
                    Session.recorded_seconds,
                    Session.active_seconds,
                    func.min(facts.c.day).label("day"),
                )
                .join(facts, facts.c.session_id == Session.id)
                .where(facts.c.key == key)
                .group_by(Session.id)
                .order_by(Session.start_time.desc(), Session.id)
                .limit(20),
            ).mappings()
        ]
        return {
            "item": item,
            "days": days,
            "months": months,
            "recent_sessions": recent,
            "day_total": item["days"],
            "limit": limit,
            "offset": offset,
        }
