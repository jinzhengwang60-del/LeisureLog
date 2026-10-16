from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select

from leisurelog.repositories.game_statistics import SQLiteGameStatistics
from leisurelog.repositories.library import METRICS
from leisurelog.repositories.models import DailyActivityRow as Daily
from leisurelog.repositories.models import GameTypeOverrideRow


class SQLiteGamePreferences(SQLiteGameStatistics):
    def exists(self, key):
        return key in self.entries()

    def save_type(self, key, primary, tags):
        self.db.merge(
            GameTypeOverrideRow(
                game_key=key,
                primary_type=primary,
                tags=tags,
                updated_at=datetime.now(timezone.utc),
            )
        )
        self.db.flush()

    def remove_type(self, key):
        self.db.execute(delete(GameTypeOverrideRow).where(GameTypeOverrideRow.game_key == key))
        self.db.flush()

    def preference_facts(self, start, end):
        entries = self.entries()
        facts = self._facts()
        month = func.strftime("%Y-%m", facts.c.day)
        rows = [
            dict(row)
            for row in self.db.execute(
                select(
                    facts.c.key,
                    month.label("month"),
                    *[func.sum(facts.c[m]).label(m) for m in METRICS],
                )
                .where(facts.c.day.between(start, end))
                .group_by(facts.c.key, month)
                .order_by(month, facts.c.key),
            ).mappings()
        ]
        # Include unnamed game-classified activities in the denominator, as untyped.
        unnamed_month = func.strftime("%Y-%m", Daily.day)
        unnamed = [
            dict(row)
            for row in self.db.execute(
                select(
                    unnamed_month.label("month"),
                    *[func.sum(getattr(Daily, m)).label(m) for m in METRICS],
                )
                .where(
                    Daily.day.between(start, end),
                    Daily.category == "game",
                    or_(Daily.content.is_(None), Daily.content == ""),
                )
                .group_by(unnamed_month)
                .order_by(unnamed_month),
            ).mappings()
        ]
        activity_days = [
            day
            for (day,) in self.db.execute(
                select(Daily.day)
                .where(Daily.day.between(start, end))
                .distinct()
                .order_by(Daily.day)
            )
        ]
        game_days = [
            day
            for (day,) in self.db.execute(
                select(Daily.day)
                .where(Daily.day.between(start, end), Daily.category == "game")
                .distinct()
                .order_by(Daily.day)
            )
        ]
        observed = {row["key"] for row in rows}
        return {
            "games": {k: entries[k] for k in observed},
            "rows": rows,
            "unnamed": unnamed,
            "activity_days": activity_days,
            "game_days": game_days,
        }
