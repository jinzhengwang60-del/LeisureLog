from dataclasses import replace
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from leisurelog.adapters.rules import RuleClassifier
from leisurelog.domain.classification import ClassificationPipeline
from leisurelog.domain.models import ActivityEvent, Classification


def sample(url=None):
    now = datetime.now(timezone.utc)
    return ActivityEvent("1", "test", "stream", "pc", now, now, "CHROME.EXE", "Example", url)


def test_rule_domain_boundary_and_combined_conditions(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        """rules:
  - id: web
    match: {app: chrome.exe, domain: bilibili.com}
    category: video
  - id: fallback
    match: {title_contains: example}
    category: other
""",
        encoding="utf-8",
    )
    classifier = RuleClassifier(path)
    assert classifier.classify(sample("https://www.bilibili.com/x")).category == "video"
    assert classifier.classify(sample("https://evilbilibili.com")).category == "other"
    assert classifier.classify(sample("https://bilibili.com.evil.test")).category == "other"
    assert (
        classifier.classify(replace(sample("https://bilibili.com"), app="other")).category
        == "other"
    )


def test_manual_priority_even_when_explicit_unknown():
    class Plugin:
        def classify(self, event):
            return Classification(category="game", origin="plugin")

    pipeline = ClassificationPipeline([Plugin()])
    assert pipeline.classify(sample(), None).origin == "plugin"
    override = Classification(category="unknown", origin="manual")
    assert pipeline.classify(sample(), override) == override
    assert ClassificationPipeline([]).classify(sample(), None).category == "unknown"


def test_invalid_rule_fails_fast(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("rules:\n  - id: empty\n    match: {}\n    category: game\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        RuleClassifier(path)
