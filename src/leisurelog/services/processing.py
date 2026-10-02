from dataclasses import replace
from datetime import datetime

from leisurelog.domain.browser import resolve_browser
from leisurelog.domain.classification import ClassificationPipeline
from leisurelog.domain.daily import daily_activity
from leisurelog.domain.games import GameClassifier
from leisurelog.domain.idle import apply_idle
from leisurelog.domain.learned_rules import LearnedRuleClassifier, is_browser, remember
from leisurelog.domain.library import identities
from leisurelog.domain.models import Classification
from leisurelog.domain.ports import ActivitySource, Repository
from leisurelog.domain.sessionization import merge_sessions
from leisurelog.domain.timing import resolve_timing


class ProcessingService:
    def __init__(self, repo: Repository, pipeline: ClassificationPipeline, gap_seconds: float):
        self.repo, self.pipeline, self.gap_seconds = repo, pipeline, gap_seconds
        self.last_work = {}

    def rebuild_changed(self) -> dict:
        scope = self.repo.processing_scope(self.gap_seconds)
        if not scope:
            self.repo.clear_changes()
            self.last_work = {"mode": "unchanged", "processed_windows": 0, "components": 0}
            return self.repo.counts()
        # Bound SQL expression size for exceptionally fragmented bulk imports.
        return self.rebuild(scope if len(scope) <= 128 else None)

    def rebuild(self, scope=None) -> dict:
        overrides = self.repo.overrides(scope)
        pipeline = ClassificationPipeline(
            [
                LearnedRuleClassifier(self.repo.learned_rules()),
                *self.pipeline.classifiers,
                GameClassifier(self.repo.games()),
            ]
        )
        windows = self.repo.events(scope=scope)
        for event in windows:
            self.repo.save_classification(
                replace(event, classification=pipeline.classify(event, overrides.get(event.id)))
            )
        events = [
            replace(
                e,
                classification=pipeline.classify(
                    e, overrides[e.id] if e.id in overrides else overrides.get(e.window_event_id)
                ),
            )
            for e in resolve_browser(windows, self.repo.browser_events(scope=scope))
        ]
        timing = self.repo.timing_overrides(scope)
        events = [
            replace(e, timing_policy=choice[0], timing_origin=choice[1])
            for e in events
            for choice in [resolve_timing(e, timing, self.pipeline.timing_rules)]
        ]
        self.repo.save_resolved(events)
        sessions = merge_sessions(events, self.gap_seconds)
        idle = self.repo.idle_events(scope=scope)
        apply_idle(sessions, events, idle)
        self.repo.register_content(identities(sessions))
        self.repo.replace_sessions(sessions, scope)
        self.repo.prune_resolved(scope)
        self.repo.replace_daily(daily_activity(sessions, events, idle), scope)
        self.repo.clear_changes()
        self.last_work = {
            "mode": "full" if scope is None else "incremental",
            "processed_windows": len(windows),
            "components": 0 if scope is None else len(scope),
        }
        return self.repo.counts()

    def sync(
        self, source: ActivitySource, start: datetime, end: datetime, buckets: list[str] | None
    ):
        records = source.fetch(start, end, buckets)
        changed = sum(self.repo.ingest(record) for record in records)
        return {"fetched": len(records), "changed": changed, **self.rebuild_changed()}

    def override(self, event_id: str, value: Classification | None):
        self.repo.set_override(event_id, value)
        return self.rebuild_changed()

    def override_many(
        self, event_ids: list[str], value: Classification | None, remember_scope: str | None = None
    ):
        selected = self.repo.resolved_events(ids=event_ids)
        existing = {event.id for event in selected}
        if any(key not in existing for key in event_ids):
            raise KeyError("One or more selected events no longer exist")
        if remember_scope is not None:
            if value is None:
                raise ValueError("A classification is required")
            self.repo.save_rule(remember(selected, remember_scope, value))
        for key in event_ids:
            self.repo.set_override(key, value)
        return {
            "updated": len(event_ids),
            **(self.rebuild() if remember_scope is not None else self.rebuild_changed()),
        }

    def remember_app(self, source: str, app: str, value: Classification):
        """Save an app-wide rule without marking any record as a manual correction."""
        if is_browser(app):
            raise ValueError("Browsers mix many sites; classify them by website instead")
        event = self.repo.app_event(source, app)
        if event is None:
            raise KeyError("No activity recorded for this app")
        self.repo.save_rule(remember([event], "app", value))
        return self.rebuild()

    def timing_many(self, event_ids, policy):
        existing = {e.id for e in self.repo.resolved_events(ids=event_ids)}
        if any(key not in existing for key in event_ids):
            raise KeyError("Selected activity no longer exists")
        for key in event_ids:
            self.repo.set_timing_override(key, policy)
        return {"updated": len(event_ids), **self.rebuild_changed()}
