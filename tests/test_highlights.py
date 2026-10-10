"""The home page headline: the day's leisure, independent of list filters."""

from tests.test_pipeline import WINDOW
from tests.test_unclassified import add

pytest_plugins = ["tests.test_pipeline"]


def test_highlights_rank_leisure_and_ignore_filters(app_context):
    client, _, payloads, _, _ = app_context
    add(payloads, 3, 400, "cloudmusic.exe", "Hey Jude", 120)
    add(payloads, 4, 600, "WINWORD.EXE", "报告.docx", 90)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    rule = {"source": "activitywatch", "app": "cloudmusic.exe", "category": "music",
            "content": "网易云音乐"}
    client.post("/api/classification/app-rules", json=rule).raise_for_status()
    day = client.get("/api/events").json()[0]["start_time"][:10]

    full = client.get("/api/dashboard", params={"day": day}).json()["highlights"]
    filtered = client.get(
        "/api/dashboard", params={"day": day, "category": "unknown"}
    ).json()["highlights"]
    assert full == filtered
    assert full["groups"]["unknown"] >= 90
    names = [(a["category"], a["content"]) for a in full["top_activities"]]
    assert ("music", "网易云音乐") in names
    assert full["leisure_seconds"] == sum(full["leisure_by_category"].values())
    assert all(a["category"] != "unknown" for a in full["top_activities"])
