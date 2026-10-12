from datetime import datetime, timedelta, timezone

from tests.test_pipeline import START, WINDOW

pytest_plugins = ["tests.test_pipeline"]
BEIJING = timezone(timedelta(hours=8))


def test_ribbon_matches_dashboard_items_and_filters(app_context):
    client, _, payloads, _, _ = app_context
    payloads.append(
        {
            "id": 3,
            "timestamp": (START + timedelta(minutes=10)).isoformat(),
            "duration": 120,
            "data": {"app": "Weixin.exe", "title": "微信"},
        }
    )
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    day = START.astimezone(BEIJING).date().isoformat()
    board = client.get("/api/dashboard", params={"day": day, "limit": 1000}).json()
    strip = client.get("/api/dashboard/ribbon", params={"day": day}).json()
    assert strip["day"] == day
    assert sorted(i["id"] for i in strip["items"]) == sorted(i["id"] for i in board["items"])
    # Items are in time order, carry epoch milliseconds and only the fields the strip draws.
    starts = [i["start"] for i in strip["items"]]
    assert starts == sorted(starts)
    first = strip["items"][0]
    assert set(first) == {
        "id",
        "start",
        "end",
        "app",
        "category",
        "content",
        "active_seconds",
        "purpose",
        "project_id",
    }
    match = next(i for i in board["items"] if i["id"] == first["id"])
    assert first["purpose"] == match["context"]["purpose"]
    assert first["project_id"] == match["context"]["project_id"]
    assert first["start"] == round(datetime.fromisoformat(match["start_time"]).timestamp() * 1000)
    # Filters behave exactly like the activity list.
    games = client.get("/api/dashboard/ribbon", params={"day": day, "category": "game"}).json()
    assert games["items"] and all(i["category"] == "game" for i in games["items"])
    found = client.get("/api/dashboard/ribbon", params={"day": day, "query": "微信"}).json()
    assert [i["app"] for i in found["items"]] == ["Weixin.exe"]
    other_day = client.get("/api/dashboard/ribbon", params={"day": "2020-01-01"}).json()
    assert other_day["items"] == []
