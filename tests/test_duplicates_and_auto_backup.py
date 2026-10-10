"""Same-named library items from different programs, and the weekly automatic backup."""

from datetime import datetime, timedelta, timezone

from leisurelog.analytics.library import same_name_key
from tests.test_pipeline import WINDOW
from tests.test_unclassified import add

pytest_plugins = ["tests.test_pipeline"]


def remember(client, app, category, content):
    client.post("/api/classification/app-rules", json={
        "source": "activitywatch", "app": app, "category": category, "content": content,
    }).raise_for_status()


def test_same_name_key_ignores_spacing_width_and_case():
    assert same_name_key("棕色尘埃 2") == same_name_key("棕色尘埃2")
    assert same_name_key("Your Fiancée") == same_name_key("your  fiancée")
    assert same_name_key("ＡＢＣ·D") == same_name_key("abc d")
    assert same_name_key("原神") != same_name_key("崩坏")


def test_duplicates_are_found_and_merged_together(app_context):
    client, _, payloads, _, _ = app_context
    add(payloads, 3, 400, "cloudmusic.exe", "Hey Jude", 120)
    add(payloads, 4, 600, "QQMusic.exe", "Yesterday", 60)
    add(payloads, 5, 700, "Weixin.exe", "微信", 30)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    remember(client, "cloudmusic.exe", "music", "听歌")
    remember(client, "QQMusic.exe", "music", "听 歌")
    remember(client, "Weixin.exe", "social", "听歌")  # same name, other category: not a duplicate

    groups = client.get("/api/library/duplicates").json()["groups"]
    assert len(groups) == 1
    group = groups[0]
    assert group["category"] == "music" and len(group["items"]) == 2
    assert group["items"][0]["active_seconds"] >= group["items"][1]["active_seconds"]
    assert group["target_id"] == group["items"][0]["id"]

    items = client.get("/api/library").json()["items"]
    social = next(i for i in items if i["category"] == "social")
    refused = client.post("/api/library/duplicates/merge", json={"groups": [
        {"target_id": group["target_id"], "source_ids": [group["items"][1]["id"]]},
        {"target_id": group["target_id"], "source_ids": [social["id"]]},
    ]})
    assert refused.status_code == 422
    assert len(client.get("/api/library/duplicates").json()["groups"]) == 1  # nothing changed

    merged = client.post("/api/library/duplicates/merge", json={"groups": [
        {"target_id": group["target_id"], "source_ids": [group["items"][1]["id"]]},
    ]})
    assert merged.status_code == 200, merged.text
    assert merged.json() == {"merged": 1, "groups": []}
    music = [i for i in client.get("/api/library").json()["items"] if i["category"] == "music"]
    assert len(music) == 1
    assert music[0]["active_seconds"] == group["active_seconds"]


def test_automatic_backups_are_due_weekly_pruned_and_never_touch_manual_ones(app_context):
    client, app, _, _, _ = app_context
    storage = app.state.storage
    manual = client.post("/api/storage/backups").json()["name"]
    # Backups record the real time they were made; "now" is moved relative to that.
    now = datetime.now(timezone.utc)
    soon, week_later = now + timedelta(days=1), now + timedelta(days=8)
    assert storage.backup_if_due(7, 2, now=soon) is None  # a fresh manual backup counts
    first = storage.backup_if_due(7, 2, now=week_later)
    assert first["automatic"] is True
    assert storage.backup_if_due(7, 2, now=soon) is None
    second = storage.backup_if_due(7, 2, now=week_later)
    third = storage.backup_if_due(7, 2, now=week_later)
    names = {item["name"]: item["automatic"] for item in storage.overview()["backups"]}
    assert names[manual] is False
    assert first["name"] not in names  # the oldest automatic one was pruned
    assert {second["name"], third["name"]} <= set(names)
    assert sum(names.values()) == 2
    assert storage.backup_if_due(0, 2, now=now + timedelta(days=99)) is None  # 0 turns it off
