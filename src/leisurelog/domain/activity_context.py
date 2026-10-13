"""Activity purpose and project attribution, independent of content classification."""

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from leisurelog.domain.learned_rules import is_browser, match_value, remember
from leisurelog.domain.models import ActivityContext, Classification

Purpose = Literal[
    "work", "study", "create", "communication", "leisure", "system", "other", "unknown"
]

PURPOSES = {
    "work": "工作",
    "study": "学习",
    "create": "创作",
    "communication": "沟通",
    "leisure": "娱乐",
    "system": "系统操作",
    "other": "其他",
    "unknown": "用途待确认",
}


class ContextClassifier(Protocol):
    def classify_context(self, event) -> dict | None: ...


@dataclass(frozen=True)
class ContextRule:
    id: str
    source: str
    app: str
    scope: str
    value: str
    assignments: dict


def remember_context(events, scope: str, assignments: dict, match_text=None) -> ContextRule:
    if scope == "app" and any(is_browser(e.app) for e in events):
        raise ValueError("Browser purpose must be scoped to a title, URL or website")
    if scope == "title_contains":
        text = (match_text or "").strip().casefold()
        keys = {(e.source, e.app.casefold()) for e in events}
        if len(keys) != 1 or not 2 <= len(text) <= 300:
            raise ValueError("A keyword rule needs one application and 2 to 300 characters")
        if any(text not in event.title.casefold() for event in events):
            raise ValueError("The keyword must occur in every selected activity title")
        source, app = keys.pop()
        if not app:
            raise ValueError("The selected application is empty")
        identity = json.dumps([source, app, scope, text], ensure_ascii=False)
        return ContextRule(
            hashlib.sha256(identity.encode()).hexdigest(), source, app, scope, text, assignments
        )
    if match_text is not None:
        raise ValueError("Only keyword rules accept a matching keyword")
    rule = remember(events, scope, Classification())
    return ContextRule(rule.id, rule.source, rule.app, rule.scope, rule.value, assignments)


class LearnedContextClassifier:
    def __init__(self, rules):
        self.rules = sorted(
            rules,
            key=lambda r: (
                {"url": 0, "title": 1, "title_contains": 2, "domain": 3, "app": 4}[r.scope],
                -len(r.value) if r.scope == "title_contains" else 0,
            ),
        )

    def classify_context(self, event):
        choices = {}
        rule_ids = {}
        for rule in self.rules:
            if context_rule_matches(event, rule):
                for key, value in rule.assignments.items():
                    if key not in choices:
                        choices[key] = value
                        rule_ids[key] = rule.id
        return {**choices, "origin": "learned", "rule_ids": rule_ids} if choices else None


def context_rule_matches(event, rule):
    return (
        event.source == rule.source
        and event.app.casefold() == rule.app
        and (
            rule.value in event.title.casefold()
            if rule.scope == "title_contains"
            else match_value(event, rule.scope) == rule.value
        )
    )


class CategoryPurposeClassifier:
    """Conservative defaults: video, reading, browsers and editors have ambiguous purposes."""

    MAPPING = {
        "work": "work",
        "study": "study",
        "learning": "study",
        "create": "create",
        "game": "leisure",
        "film": "leisure",
        "anime": "leisure",
        "music": "leisure",
        "social": "communication",
        "meeting": "communication",
        "system": "system",
    }

    def classify_context(self, event):
        purpose = self.MAPPING.get(event.classification.category)
        return {"purpose": purpose, "origin": "category"} if purpose else None


def resolve_context(event, classifiers, overrides):
    context = ActivityContext()
    chosen = set()
    for classifier in classifiers:
        result = classifier.classify_context(event) or {}
        for key in ("purpose", "project_id"):
            if key in result and key not in chosen:
                origin = "purpose_origin" if key == "purpose" else "project_origin"
                context = replace(
                    context, **{key: result[key], origin: result.get("origin", "rule")}
                )
                chosen.add(key)
    manual = {**overrides.get(event.window_event_id, {}), **overrides.get(event.id, {})}
    for key in ("purpose", "project_id"):
        if (
            key in manual
            and manual[key] != "__auto__"
            and not (key == "purpose" and manual[key] is None)
        ):
            origin = "purpose_origin" if key == "purpose" else "project_origin"
            context = replace(context, **{key: manual[key], origin: "manual"})
    return context


class ContextStore(Protocol):
    def projects(self) -> list[dict]: ...
    def project(self, project_id: str) -> dict: ...
    def save_project(self, project_id: str | None, values: dict) -> dict: ...
    def context_overrides(self, scope=None) -> dict: ...
    def context_rules(self) -> list[ContextRule]: ...
    def save_context(self, event, values: dict | None) -> None: ...
    def save_context_rule(self, rule: ContextRule) -> None: ...
    def delete_context_rule(self, rule_id: str) -> None: ...
    def project_facts(self, start, end, project_id=None) -> dict: ...
    def week_facts(self, start, end) -> dict: ...
    def pending_facts(self, start, end, limit, offset, search) -> dict: ...
    def pending_events(self, start, end, source, app, website, limit, offset) -> dict: ...
    def decision_snapshot(self, event_ids, rule_id=None) -> dict: ...
    def restore_decisions(self, snapshot) -> None: ...
    def save_change(self, action, before, after) -> str | None: ...
    def change(self, change_id) -> dict: ...
    def changes(self, limit, offset) -> dict: ...
    def mark_undone(self, change_id) -> None: ...
    def project_lifetime_seconds(self) -> dict: ...
