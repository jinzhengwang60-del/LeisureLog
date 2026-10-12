"""Project lifecycle and user attribution; raw events and classification stay independent."""

from leisurelog.domain.activity_context import PURPOSES, ContextStore, remember_context


class ActivityContextService:
    def __init__(self, store: ContextStore, processing):
        self.store, self.processing = store, processing

    def attribute(self, event_ids, assignments, remember_scope=None, match_text=None):
        if "purpose" in assignments and assignments["purpose"] not in (*PURPOSES, None):
            raise ValueError("Unknown purpose")
        project_id = assignments.get("project_id")
        if project_id:
            self.store.project(project_id)
        selected = self.processing.repo.resolved_events(ids=event_ids)
        if {e.id for e in selected} != set(event_ids):
            raise KeyError("Selected events no longer exist")
        if remember_scope:
            if not assignments or assignments.get("purpose", "unknown") is None:
                raise ValueError("A remembered rule must contain an explicit choice")
            self.store.save_context_rule(
                remember_context(selected, remember_scope, assignments, match_text)
            )
        elif match_text is not None:
            raise ValueError("Matching keywords require a remembered keyword rule")
        for event in selected:
            self.store.save_context(event, assignments)
            self.processing.repo.mark_context_changed(event)
        result = self.processing.rebuild() if remember_scope else self.processing.rebuild_changed()
        return {"updated": len(selected), **result}

    def restore(self, event_ids):
        selected = self.processing.repo.resolved_events(ids=event_ids)
        if {e.id for e in selected} != set(event_ids):
            raise KeyError("Selected events no longer exist")
        for event in selected:
            self.store.save_context(event, None)
            self.processing.repo.mark_context_changed(event)
        return {"updated": len(selected), **self.processing.rebuild_changed()}

    def remove_rule(self, rule_id):
        self.store.delete_context_rule(rule_id)
        return self.processing.rebuild()
