from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select

from leisurelog.adapters.rules import RuleClassifier
from leisurelog.domain.classification import ClassificationPipeline
from leisurelog.domain.content import TitleContentExtractor
from leisurelog.domain.learned_rules import LearnedRuleClassifier, remember
from leisurelog.domain.models import Classification
from leisurelog.repositories.models import RawEventRow
from leisurelog.repositories.sqlite import SQLiteRepository
from tests.test_browser import add_page, page
from tests.test_pipeline import WINDOW, event

pytest_plugins = ["tests.test_pipeline"]
ROOT = Path(__file__).resolve().parents[1]


def web(title, url="https://manga.bilibili.com/mc31347/746990"):
    return replace(event("test", 0, 120, app="msedge.exe"), title=title, url=url)


@pytest.mark.parametrize(
    "title, expected",
    [
        (
            "7-54 - 乔乔的奇妙冒险 彩色版（1-8部） - 漫画全集在线观看 - 哔哩哔哩漫画",
            "乔乔的奇妙冒险 彩色版（1-8部）",
        ),
        (
            "7-55 - 乔乔的奇妙冒险 彩色版（1-8部） - 漫画全集在线观看 - 哔哩哔哩漫画",
            "乔乔的奇妙冒险 彩色版（1-8部）",
        ),
        ("作品 - 有意义的副标题 - 漫画全集在线观看 - 哔哩哔哩漫画", "作品 - 有意义的副标题"),
        ("个人中心 - 哔哩哔哩漫画", "哔哩哔哩漫画"),
        ("", "哔哩哔哩漫画"),
    ],
)
def test_configured_manga_name_and_conservative_fallback(title, expected):
    value = RuleClassifier(ROOT / "config/rules.yaml").classify(web(title))
    assert value.category == "reading" and value.content == expected


@pytest.mark.parametrize(
    "title, url, expected",
    [
        ("如何写好代码_哔哩哔哩_bilibili", "https://www.bilibili.com/video/BV1", "如何写好代码"),
        ("音乐现场 - YouTube", "https://www.youtube.com/watch?v=1", "音乐现场"),
        ("音乐现场 - YouTube", "https://www.youtube.com/", "YouTube"),
        ("未知标题", "https://unknown.example/video/1", None),
    ],
)
def test_video_titles_and_unrecognized_sites(title, url, expected):
    value = RuleClassifier(ROOT / "config/rules.yaml").classify(web(title, url))
    assert (value.content if value else None) == expected


def test_extractor_validation_and_bounds():
    with pytest.raises(ValueError, match="named content group"):
        TitleContentExtractor("(.+)")
    extractor = TitleContentExtractor("(?P<content>.*) - Site")
    assert extractor.extract(" - Site") is None
    assert extractor.extract("a" * 301 + " - Site") is None
    assert extractor.extract("a" * 1001 + " - Site") is None
    assert extractor.extract("  名称   说明 - Site") == "名称 说明"
    assert extractor.extract("page - Site suffix") is None


def test_page_memory_scope_priority_and_title_change():
    original = web("旧标题", "https://example.com/watch?v=1#top")
    url_rule = remember([original], "url", Classification("video", "具体视频"))
    broad = remember([original], "domain", Classification("reading", "整个网站"))
    classifier = LearnedRuleClassifier([broad, url_rule])
    changed = replace(original, title="新标题", url="https://example.com/watch?v=1#bottom")
    assert classifier.classify(changed).content == "具体视频"
    assert (
        classifier.classify(replace(changed, url="https://example.com/watch?v=2")).content
        == "整个网站"
    )
    assert classifier.classify(replace(changed, app="chrome.exe")) is None
    assert (
        ClassificationPipeline([classifier])
        .classify(changed, Classification("work", origin="manual"))
        .category
        == "work"
    )
    with pytest.raises(ValueError, match="empty"):
        remember([replace(original, url="edge://settings")], "url", Classification("work"))


def test_content_names_rebuild_statistics_and_page_rule_persistence(app_context):
    client, app, payloads, _, _ = app_context
    title = "7-54 - 乔乔的奇妙冒险 彩色版（1-8部） - 漫画全集在线观看 - 哔哩哔哩漫画"
    payloads[:] = [
        {
            **payloads[0],
            "duration": 120,
            "data": {"app": "msedge.exe", "title": title + " - Microsoft Edge"},
        }
    ]
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    add_page(
        app,
        replace(
            page(start=0, duration=120),
            title=title,
            url="https://manga.bilibili.com/mc31347/746990",
        ),
    )
    client.post("/api/reprocess").raise_for_status()
    current = client.get("/api/events").json()[0]
    assert current["classification"]["content"] == "乔乔的奇妙冒险 彩色版（1-8部）"
    summary = client.get("/api/statistics?start=2026-09-29&end=2026-09-29").json()
    assert summary["contents"][0]["content"] == current["classification"]["content"]
    assert summary["contents"][0]["recorded_seconds"] == 120
    result = client.put(
        "/api/events/overrides",
        json={
            "event_ids": [current["id"]],
            "category": "reading",
            "content": "用户命名",
            "remember_scope": "url",
        },
    )
    assert result.status_code == 200, result.text
    client.delete(f"/api/events/{current['id']}/override").raise_for_status()
    client.post("/api/reprocess").raise_for_status()
    assert client.get("/api/events").json()[0]["classification"]["content"] == "用户命名"
    assert client.get("/api/events").json()[0]["classification"]["origin"] == "learned"
    with app.state.sessions() as db:
        assert len(list(db.scalars(select(RawEventRow)))) == 2
        assert SQLiteRepository(db).events()[0].url is None
    rule = client.get("/api/classification/rules").json()[0]
    assert rule["scope"] == "url" and rule["value"] == current["url"]
    client.delete(f"/api/classification/rules/{rule['id']}").raise_for_status()
    assert (
        client.get("/api/events").json()[0]["classification"]["content"]
        == "乔乔的奇妙冒险 彩色版（1-8部）"
    )
