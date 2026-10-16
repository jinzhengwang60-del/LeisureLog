"""Source-only diagnostic contribution used to verify the host, without activity details."""

from datetime import date, timedelta

from leisurelog.plugin_api import PluginContributions, ScheduledTask, SummaryQuery, TaskBudget


class SummaryProbe:
    def __init__(self, reader):
        self._reader = reader

    def run(self, context):
        if context.stop_requested():
            return
        today = date.today()
        self._reader.read(SummaryQuery(today - timedelta(days=6), today))


def create(context):
    if context.summary is None:
        raise ValueError("诊断插件需要汇总授权")
    return PluginContributions(
        tasks=(
            ScheduledTask(
                "summary-probe",
                SummaryProbe(context.summary),
                interval_seconds=60,
                budget=TaskBudget(run_timeout_seconds=2, stop_timeout_seconds=1),
            ),
        )
    )
