"""Detached aggregate projection using existing Beijing calendar-day facts."""

from sqlalchemy import func, select

from leisurelog.domain.plugin_contracts import ActivitySummary, CategoryTotal, SummaryQuery
from leisurelog.repositories.models import DailyActivityRow


class SQLitePluginSummary:
    def __init__(self, sessions):
        self._sessions = sessions

    def read(self, query: SummaryQuery) -> ActivitySummary:
        row = DailyActivityRow
        statement = select(row.category, func.sum(row.active_seconds)).where(
            row.day >= query.start,
            row.day <= query.end,
        )
        if query.purpose is not None:
            statement = statement.where(row.purpose == query.purpose)
        if query.project_id is not None:
            statement = statement.where(row.project_id == query.project_id)
        statement = statement.group_by(row.category).order_by(row.category)
        with self._sessions() as db:
            totals = tuple(
                CategoryTotal(category, float(seconds))
                for category, seconds in db.execute(statement)
            )
        return ActivitySummary(sum(total.active_seconds for total in totals), totals)
