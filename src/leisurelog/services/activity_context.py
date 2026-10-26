"""Project lifecycle and user attribution; raw events and classification stay independent."""

import hashlib
import json
from dataclasses import asdict, replace
from itertools import islice

from leisurelog.domain.activity_context import (
    PURPOSES,
    CategoryPurposeClassifier,
    ContextStore,
    LearnedContextClassifier,
    context_rule_matches,
    remember_context,
    resolve_context,
)


class PreviewChanged(ValueError):
    pass


class DecisionChanged(ValueError):
    pass


class ActivityContextService:
    def __init__(self, store: ContextStore, processing):
        self.store, self.processing = store, processing

    def _selected(self, event_ids, assignments):
        if "purpose" in assignments and assignments["purpose"] not in (*PURPOSES, None):
            raise ValueError("Unknown purpose")
        project_id = assignments.get("project_id")
        if project_id:
            self.store.project(project_id)
        selected = self.processing.repo.resolved_events(ids=event_ids)
        if {e.id for e in selected} != set(event_ids):
            raise KeyError("Selected events no longer exist")
        return selected

    def preview(self, event_ids, assignments, remember_scope, match_text=None):
        selected = self._selected(event_ids, assignments)
        if not remember_scope or assignments.get("purpose", "unknown") is None:
            raise ValueError("A remembered rule must contain an explicit choice")
        rule = remember_context(selected, remember_scope, assignments, match_text)
        rules = self.store.context_rules()
        old = next((value for value in rules if value.id == rule.id), None)
        if old:
            rule = replace(rule, assignments={**old.assignments, **rule.assignments})
        proposed = [rule, *(value for value in rules if value.id != rule.id)]
        classifiers = [
            LearnedContextClassifier(proposed),
            *self.processing.pipeline.context_classifiers,
            CategoryPurposeClassifier(),
        ]
        selected_ids = set(event_ids)
        digest = hashlib.sha256(
            json.dumps(
                [asdict(rule), sorted(selected_ids)], ensure_ascii=False, sort_keys=True
            ).encode()
        )
        counts = {"matched_events": 0, "changed_events": 0, "manual_protected_events": 0}
        samples = []
        candidates = iter(self.processing.repo.context_candidates(rule))
        while batch := list(islice(candidates, 256)):
            overrides = self.store.context_overrides({event.window_event_id for event in batch})
            for event in batch:
                if event.id in selected_ids:
                    overrides[event.id] = {**overrides.get(event.id, {}), **assignments}
            for event in batch:
                after = resolve_context(event, classifiers, overrides)
                changed = any(
                    getattr(event.context, key) != getattr(after, key)
                    for key in ("purpose", "project_id")
                )
                protected = event.id not in selected_ids and any(
                    getattr(after, "purpose_origin" if key == "purpose" else "project_origin")
                    == "manual"
                    for key in rule.assignments
                )
                counts["matched_events"] += 1
                counts["changed_events"] += changed
                counts["manual_protected_events"] += protected
                digest.update(
                    json.dumps(
                        [asdict(event), asdict(after)],
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ).encode()
                )
                if len(samples) < 6:
                    samples.append(
                        {
                            "id": event.id,
                            "title": event.title,
                            "url": event.url,
                            "app": event.app,
                            "before": asdict(event.context),
                            "after": asdict(after),
                            "changed": changed,
                            "manual_protected": protected,
                        }
                    )
        return {
            "rule": asdict(rule),
            "selected_events": len(selected_ids),
            **counts,
            "samples": samples,
            "preview_token": digest.hexdigest(),
            "scope": "all_history",
        }

    def attribute(
        self, event_ids, assignments, remember_scope=None, match_text=None, preview_token=None
    ):
        selected = self._selected(event_ids, assignments)
        if preview_token is not None:
            if (
                not remember_scope
                or self.preview(event_ids, assignments, remember_scope, match_text)["preview_token"]
                != preview_token
            ):
                raise PreviewChanged("Rule preview is outdated; preview again")
        rule = None
        if remember_scope:
            if not assignments or assignments.get("purpose", "unknown") is None:
                raise ValueError("A remembered rule must contain an explicit choice")
            rule = remember_context(selected, remember_scope, assignments, match_text)
        elif match_text is not None:
            raise ValueError("Matching keywords require a remembered keyword rule")
        before = self.store.decision_snapshot(event_ids, rule.id if rule else None)
        if rule:
            self.store.save_context_rule(rule)
        for event in selected:
            self.store.save_context(event, assignments)
        result = (
            self.processing.rebuild()
            if remember_scope
            else self.processing.refresh_context(selected)
        )
        after = self.store.decision_snapshot(event_ids, rule.id if rule else None)
        change_id = self.store.save_change("remember" if rule else "attribute", before, after)
        return {"updated": len(selected), "change_id": change_id, **result}

    def restore(self, event_ids):
        selected = self.processing.repo.resolved_events(ids=event_ids)
        if {e.id for e in selected} != set(event_ids):
            raise KeyError("Selected events no longer exist")
        before = self.store.decision_snapshot(event_ids)
        for event in selected:
            self.store.save_context(event, None)
        result = self.processing.refresh_context(selected)
        change_id = self.store.save_change(
            "restore", before, self.store.decision_snapshot(event_ids)
        )
        return {"updated": len(selected), "change_id": change_id, **result}

    def remove_rule(self, rule_id):
        before = self.store.decision_snapshot([], rule_id)
        self.store.delete_context_rule(rule_id)
        result = self.processing.rebuild()
        change_id = self.store.save_change(
            "remove_rule", before, self.store.decision_snapshot([], rule_id)
        )
        return {"change_id": change_id, **result}

    def undo(self, change_id):
        change = self.store.change(change_id)
        if change["undone_at"] is not None:
            raise DecisionChanged("This change has already been undone")
        after = change["after"]
        rule_id = next(iter(after.get("rules", {})), None)
        current = self.store.decision_snapshot(list(after["overrides"]), rule_id)
        if current != after:
            raise DecisionChanged(
                "These decisions changed after this operation; undo newer changes first"
            )
        self.store.restore_decisions(change["before"])
        result = self.processing.rebuild()
        self.store.mark_undone(change_id)
        return {"undone": change_id, **result}

    def explain(self, event_id):
        events = self.processing.repo.resolved_events(ids=[event_id])
        if not events:
            raise KeyError(event_id)
        event = events[0]
        rules = LearnedContextClassifier(self.store.context_rules())
        classifiers = [
            rules,
            *self.processing.pipeline.context_classifiers,
            CategoryPurposeClassifier(),
        ]
        overrides = self.store.context_overrides({event.window_event_id})
        fields = {}
        for classifier in classifiers:
            choice = classifier.classify_context(event) or {}
            for key in ("purpose", "project_id"):
                if key in choice and key not in fields:
                    fields[key] = {
                        "origin": choice.get("origin", "rule"),
                        "rule_id": choice.get("rule_ids", {}).get(key),
                    }
        manual = {**overrides.get(event.window_event_id, {}), **overrides.get(event.id, {})}
        for key in ("purpose", "project_id"):
            if (
                key in manual
                and manual[key] != "__auto__"
                and not (key == "purpose" and manual[key] is None)
            ):
                fields[key] = {
                    "origin": "manual",
                    "rule_id": None,
                    "event_id": event.id
                    if key in overrides.get(event.id, {})
                    else event.window_event_id,
                }
            fields.setdefault(key, {"origin": "fallback", "rule_id": None})
            fields[key]["value"] = getattr(event.context, key)
        matched = [asdict(rule) for rule in rules.rules if context_rule_matches(event, rule)]
        for rule in matched:
            rule["effective_fields"] = [
                key for key, value in fields.items() if value["rule_id"] == rule["id"]
            ]
        return {
            "event_id": event.id,
            "context": asdict(event.context),
            "fields": fields,
            "matched_rules": matched,
            "priority": [
                "manual",
                "url",
                "title",
                "title_contains",
                "domain",
                "app",
                "config",
                "category",
                "fallback",
            ],
        }
