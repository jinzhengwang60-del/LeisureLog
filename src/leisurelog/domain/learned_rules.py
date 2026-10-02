"""Reusable user decisions, independent of storage and external sources."""

import hashlib
import json
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from leisurelog.domain.models import ActivityEvent, Classification


@dataclass(frozen=True)
class LearnedRule:
    id: str
    source: str
    app: str
    scope: str
    value: str
    classification: Classification


def match_value(event: ActivityEvent, scope: str) -> str:
    if scope == "app":
        return event.app.casefold()
    if scope == "title":
        return event.title
    if scope == "url":
        try:
            parsed = urlsplit(event.url or "")
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return ""
            return parsed._replace(fragment="").geturl()
        except ValueError:
            return ""
    if scope == "domain":
        try:
            return (urlsplit(event.url or "").hostname or "").casefold()
        except ValueError:
            return ""
    raise ValueError("Unknown rule scope")


def remember(events: list[ActivityEvent], scope: str, value: Classification) -> LearnedRule:
    keys = {(e.source, e.app.casefold(), match_value(e, scope)) for e in events}
    if len(keys) != 1:
        raise ValueError("Selected records must share the same matching scope")
    source, app, matched = keys.pop()
    if not app or not matched:
        raise ValueError("The selected matching field is empty")
    identity = json.dumps([source, app, scope, matched], ensure_ascii=False)
    return LearnedRule(
        hashlib.sha256(identity.encode()).hexdigest(),
        source,
        app,
        scope,
        matched,
        replace(value, origin="learned"),
    )


# Apps whose content varies page by page; a rule for the whole app would misfile everything.
BROWSER_APPS = frozenset(
    {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
     "360se.exe", "qqbrowser.exe", "sogouexplorer.exe"}
)


def is_browser(app: str) -> bool:
    return app.casefold() in BROWSER_APPS


class LearnedRuleClassifier:
    def __init__(self, rules: list[LearnedRule]):
        # Repository supplies newest first; specific matches take priority over an app rule.
        self.rules = sorted(
            rules, key=lambda rule: {"url": 0, "title": 1, "domain": 2, "app": 3}.get(rule.scope, 3)
        )

    def classify(self, event: ActivityEvent) -> Classification | None:
        for rule in self.rules:
            if (
                event.source == rule.source
                and event.app.casefold() == rule.app
                and match_value(event, rule.scope) == rule.value
            ):
                return rule.classification
        return None
