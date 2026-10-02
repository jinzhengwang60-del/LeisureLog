"""Explicit timing choices; foreground/audible evidence never proves human attention."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TimingRule:
    id: str
    policy: str
    app: str | None = None
    category: str | None = None


def resolve_timing(event, overrides, rules):
    key = event.id if event.id in overrides else event.window_event_id
    choice = overrides.get(key)
    if choice and choice != "default":
        return choice, "manual"
    for rule in rules:
        if rule.app and rule.app.casefold() != event.app.casefold():
            continue
        if rule.category and rule.category != event.classification.category:
            continue
        return rule.policy, "rule:" + rule.id
    return "afk", "default"


def protected_intervals(events):
    return [
        (e.start_time, e.end_time)
        for e in events
        if getattr(e, "timing_policy", "afk") == "foreground"
        or (getattr(e, "timing_policy", "afk") == "audible" and getattr(e, "audible", False))
    ]
