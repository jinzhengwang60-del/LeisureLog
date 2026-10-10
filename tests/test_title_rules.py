from datetime import datetime, timezone

import pytest

from leisurelog.adapters.rules import RuleClassifier
from leisurelog.domain.models import ActivityEvent
from tests.test_pipeline import ROOT

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
EDGE = " - 个人 - Microsoft​ Edge"
JOJO = "乔乔的奇妙冒险 彩色版（1-8部）"
MANGA = " - 漫画全集在线观看 - 哔哩哔哩漫画"


def event(app, title, url=None):
    return ActivityEvent("e", "aw", "s", "pc", NOW, NOW, app, title, url)


@pytest.mark.parametrize(
    ("app", "title", "url", "expected"),
    [
        # Edge window titles without a URL still find the manga and its name.
        ("msedge.exe", f"7-54 - {JOJO}{MANGA} 和另外 11 个页面{EDGE}", None,
         ("reading", JOJO, "rule:bilibili-manga-title")),
        ("chrome.exe", "某个视频_哔哩哔哩_bilibili - Google Chrome", None,
         ("video", "某个视频", "rule:bilibili-video-title")),
        ("chrome.exe", "某视频 - YouTube - Google Chrome", None,
         ("video", "某视频", "rule:youtube-video-title")),
        ("chrome.exe", "动态首页-哔哩哔哩 - Google Chrome", None,
         ("browsing", "哔哩哔哩", "rule:bilibili-title")),
        ("chrome.exe", "LeisureLog · 活动记录 - Google Chrome", None,
         ("other", None, "rule:leisurelog-chrome")),
        # A URL keeps priority over the title fallback.
        ("msedge.exe", f"7-51 - {JOJO}{MANGA}", "https://manga.bilibili.com/mc1/1",
         ("reading", JOJO, "rule:bilibili-manga")),
        ("explorer.exe", "下载", None, ("other", None, "rule:system-explorer")),
        ("chrome.exe", "(8) Home / X - Google Chrome", None,
         ("social", "X", "rule:x-title-chrome")),
        ("msedge.exe", "Search / X - 个人 - Microsoft Edge", None,
         ("social", "X", "rule:x-title-edge")),
        ("chrome.exe", "Home / X", "https://x.com/home", ("social", "X", "rule:x")),
    ],
)
def test_title_fallback_rules(app, title, url, expected):
    found = RuleClassifier(ROOT / "config/rules.yaml").classify(event(app, title, url))
    assert (found.category, found.content, found.origin) == expected


def test_title_rules_leave_unrelated_windows_alone():
    rules = RuleClassifier(ROOT / "config/rules.yaml")
    assert rules.classify(event("Code.exe", "README.md - LeisureLog - Visual Studio Code")) is None
    assert rules.classify(event("chrome.exe", "新标签页 - Google Chrome")) is None
