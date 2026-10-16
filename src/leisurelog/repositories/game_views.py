"""Materialize only the fixed projections used by game analysis, never ORM/SQL."""

from datetime import date, datetime

from leisurelog.domain.plugin_extensions import JsonSnapshot
from leisurelog.repositories.game_preferences import SQLiteGamePreferences


def _detached(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if type(value) is dict:
        return {key: _detached(child) for key, child in value.items()}
    if type(value) in (list, tuple):
        return [_detached(child) for child in value]
    return value


class SQLiteGameViews:
    def __init__(self, db):
        self.store = SQLiteGamePreferences(db)

    def read(self, view, parameters):
        if view == "listing":
            value = {"items": list(self.store.entries().values())}
        elif view == "detail":
            value = self.store.detail(
                parameters["key"], parameters.get("limit", 30), parameters.get("offset", 0)
            )
        elif view == "preferences":
            value = self.store.preference_facts(
                date.fromisoformat(parameters["start"]), date.fromisoformat(parameters["end"])
            )
        elif view == "options":
            value = {}
        else:
            raise ValueError("未知的宿主投影")
        return JsonSnapshot.from_value(_detached(value))
