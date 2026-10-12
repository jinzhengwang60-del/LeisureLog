from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from leisurelog.domain.content import TitleContentExtractor
from leisurelog.domain.models import ActivityEvent, Classification
from leisurelog.domain.timing import TimingRule


class Match(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: str | None = Field(default=None, min_length=1)
    domain: str | None = Field(default=None, min_length=1)
    path_prefix: str | None = Field(default=None, min_length=1)
    title_contains: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def nonempty(self):
        if not any((self.app, self.domain, self.title_contains, self.path_prefix)):
            raise ValueError("A rule must have at least one match condition")
        return self


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    match: Match
    category: str = Field(min_length=1)
    content: str | None = None
    content_title_pattern: str | None = Field(default=None, min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list)


class TimingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    policy: Literal["afk", "foreground", "audible"]
    app: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.app and not self.category:
            raise ValueError("Timing rule needs app or category")
        return self


class RuleFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[Rule]
    timing_policies: list[TimingConfig] = Field(default_factory=list)
    purpose_rules: list["PurposeRule"] = Field(default_factory=list)


class PurposeRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    match: Match
    purpose: Literal[
        "work", "study", "create", "communication", "leisure", "system", "other", "unknown"
    ]


def matches(match, event):
    try:
        parsed = urlparse(event.url or "")
        host, path = (parsed.hostname or "").casefold(), parsed.path
    except ValueError:
        host, path = "", ""
    domain = match.domain.casefold() if match.domain else None
    return (
        (not match.app or event.app.casefold() == match.app.casefold())
        and (not domain or host == domain or host.endswith("." + domain))
        and (not match.path_prefix or path.startswith(match.path_prefix))
        and (not match.title_contains or match.title_contains.casefold() in event.title.casefold())
    )


class RuleClassifier:
    def __init__(self, path: Path):
        config = RuleFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        self.rules = config.rules
        self.purpose_rules = config.purpose_rules
        if len({r.id for r in self.purpose_rules}) != len(self.purpose_rules):
            raise ValueError("Purpose rule IDs must be unique")
        self.timing_rules = [TimingRule(**r.model_dump()) for r in config.timing_policies]
        if len({r.id for r in self.timing_rules}) != len(self.timing_rules):
            raise ValueError("Timing rule IDs must be unique")
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError("Rule IDs must be unique")
        self.extractors = {
            r.id: TitleContentExtractor(r.content_title_pattern)
            for r in self.rules
            if r.content_title_pattern
        }

    def classify(self, event: ActivityEvent) -> Classification | None:
        for rule in self.rules:
            if not matches(rule.match, event):
                continue
            extractor = self.extractors.get(rule.id)
            content = (extractor.extract(event.title) if extractor else None) or rule.content
            return Classification(rule.category, content, tuple(rule.tags), "rule:" + rule.id)
        return None

    def classify_context(self, event):
        for rule in self.purpose_rules:
            if matches(rule.match, event):
                return {"purpose": rule.purpose, "origin": "config:" + rule.id}
        return None
