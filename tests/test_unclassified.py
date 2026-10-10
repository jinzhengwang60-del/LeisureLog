from datetime import timedelta

from sqlalchemy import func, select

from leisurelog.repositories.models import ManualOverrideRow
from tests.test_pipeline import START, WINDOW

pytest_plugins = ["tests.test_pipeline"]


def add(payloads, ident, offset, app, title, duration=60):
    payloads.append(
        {
            "id": ident,
            "timestamp": (START + timedelta(seconds=offset)).isoformat(),
            "duration": duration,
            "data": {"app": app, "title": title},
        }
    )


def test_report_groups_unknown_apps_and_flags_browsers(app_context):
    client, _, payloads, _, _ = app_context
    add(payloads, 3, 400, "Weixin.exe", "微信", 120)
    add(payloads, 4, 600, "Weixin.exe", "文件传输助手", 30)
    add(payloads, 5, 900, "msedge.exe", "漫画 - Microsoft Edge", 90)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    report = client.get("/api/unclassified").json()
    apps = {item["app"]: item for item in report["apps"]}
    # Classified Genshin activity never appears; unknown apps and browsers do.
    assert "GenshinImpact.exe" not in apps
    assert apps["Weixin.exe"]["browser"] is False
    assert apps["Weixin.exe"]["active_seconds"] == 150
    assert apps["Weixin.exe"]["sample_titles"][0] == "微信"
    assert apps["msedge.exe"]["browser"] is True
    assert report["app_count"] == 1
    assert report["browser_active_seconds"] == 90
    assert report["total_active_seconds"] == 240


def test_app_rule_classifies_history_and_future_without_manual_marks(app_context):
    client, app, payloads, _, _ = app_context
    add(payloads, 3, 400, "Weixin.exe", "微信", 120)
    add(payloads, 4, 600, "Weixin.exe", "文件传输助手", 30)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    # An earlier, specific correction must survive the app-wide rule.
    single = next(e for e in client.get("/api/events").json() if e["title"] == "文件传输助手")
    client.put(f"/api/events/{single['id']}/override", json={"category": "work"}).raise_for_status()

    body = {"source": "activitywatch", "app": "Weixin.exe", "category": "social"}
    result = client.post("/api/classification/app-rules", json=body)
    assert result.status_code == 200, result.text
    assert all(item["app"] != "Weixin.exe" for item in result.json()["apps"])

    events = {e["title"]: e["classification"] for e in client.get("/api/events").json()}
    assert events["微信"] == {**events["微信"], "category": "social", "origin": "learned"}
    assert events["文件传输助手"]["category"] == "work"
    assert events["文件传输助手"]["origin"] == "manual"
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ManualOverrideRow)) == 1
    rules = client.get("/api/classification/rules").json()
    assert [(r["app"], r["scope"]) for r in rules] == [("weixin.exe", "app")]

    # A later sync uses the stored rule.
    add(payloads, 5, 1200, "Weixin.exe", "新消息")
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    later = next(e for e in client.get("/api/events").json() if e["title"] == "新消息")
    assert later["classification"]["category"] == "social"

    # Deleting the rule restores the unknown state.
    client.delete(f"/api/classification/rules/{rules[0]['id']}").raise_for_status()
    assert any(i["app"] == "Weixin.exe" for i in client.get("/api/unclassified").json()["apps"])


def test_app_rule_content_name_and_rejections(app_context):
    client, _, payloads, _, _ = app_context
    add(payloads, 3, 400, "LeagueClientUx.exe", "League of Legends", 120)
    add(payloads, 4, 700, "chrome.exe", "首页 - Google Chrome", 60)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    body = {"source": "activitywatch", "app": "LeagueClientUx.exe", "category": "game",
            "content": "  英雄联盟  "}
    client.post("/api/classification/app-rules", json=body).raise_for_status()
    league = next(e for e in client.get("/api/events").json() if e["app"] == "LeagueClientUx.exe")
    assert league["classification"]["content"] == "英雄联盟"

    rejected = [
        ({"source": "activitywatch", "app": "chrome.exe", "category": "video"}, 422),
        ({"source": "activitywatch", "app": "Weixin.exe", "category": "unknown"}, 422),
        ({"source": "activitywatch", "app": "NotSeen.exe", "category": "social"}, 404),
        ({"source": "activitywatch", "app": "x.exe", "category": "social", "extra": 1}, 422),
    ]
    for payload, status in rejected:
        assert client.post("/api/classification/app-rules", json=payload).status_code == status
    assert len(client.get("/api/classification/rules").json()) == 1
    assert client.get("/unclassified").status_code == 200


def test_suggestions_are_offered_but_not_saved(app_context):
    client, _, payloads, _, _ = app_context
    add(payloads, 3, 400, "cloudmusic.exe", "Hey Jude - The Beatles", 120)
    add(payloads, 4, 600, "MyGameSetup.exe", "安装向导", 30)
    add(payloads, 5, 700, "mystery.exe", "什么都不像", 30)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    report = client.get("/api/unclassified").json()
    apps = {item["app"]: item for item in report["apps"]}
    assert apps["cloudmusic.exe"]["suggestion"] == {
        "category": "music", "content": "网易云音乐", "reason": "音乐软件",
    }
    assert apps["MyGameSetup.exe"]["suggestion"]["category"] == "system"
    assert apps["mystery.exe"]["suggestion"] is None
    assert report["suggested_count"] == 2
    # Nothing was classified just by looking.
    assert {e["classification"]["category"] for e in client.get("/api/events").json()
            if e["app"] == "cloudmusic.exe"} == {"unknown"}


def test_batch_rules_rebuild_once_and_are_all_or_nothing(app_context):
    client, _, payloads, _, _ = app_context
    add(payloads, 3, 400, "cloudmusic.exe", "Hey Jude", 120)
    add(payloads, 4, 600, "clash-verge.exe", "Clash Verge", 30)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    rule = {"source": "activitywatch", "app": "cloudmusic.exe", "category": "music"}
    bad = client.post("/api/classification/app-rules/batch", json={"rules": [
        rule, {"source": "activitywatch", "app": "never-seen.exe", "category": "system"},
    ]})
    assert bad.status_code == 404
    events = {e["app"]: e["classification"]["category"] for e in client.get("/api/events").json()}
    assert events["cloudmusic.exe"] == "unknown"
    browser = client.post("/api/classification/app-rules/batch", json={"rules": [
        {"source": "activitywatch", "app": "msedge.exe", "category": "video"},
    ]})
    assert browser.status_code == 422

    good = client.post("/api/classification/app-rules/batch", json={"rules": [
        rule, {"source": "activitywatch", "app": "clash-verge.exe", "category": "system"},
    ]})
    assert good.status_code == 200, good.text
    assert good.json()["saved"] == 2
    events = {e["app"]: e["classification"] for e in client.get("/api/events").json()}
    assert events["cloudmusic.exe"]["category"] == "music"
    assert events["clash-verge.exe"]["category"] == "system"
    assert events["clash-verge.exe"]["origin"] == "learned"
