"""ActivityWatch trims events to the requested range. Consecutive, overlapping sync windows
see different slices of one long event; together they must rebuild the whole event."""

from datetime import timedelta

from tests.test_pipeline import START

pytest_plugins = ["tests.test_pipeline"]

MIN = timedelta(minutes=1)


def window(a, b):
    return {"start": (START + a * MIN).isoformat(), "end": (START + b * MIN).isoformat()}


def piece(ident, start_min, minutes, data):
    return {
        "id": ident,
        "timestamp": (START + start_min * MIN).isoformat(),
        "duration": minutes * 60,
        "data": data,
    }


def test_cropped_slices_rebuild_long_window_and_afk_events(app_context):
    client, app, payloads, _, _ = app_context
    idle = app.state.test_idle_payloads
    # The real events run 2–14 min (window) and 1–14 min (not-afk).
    game = {"app": "GenshinImpact.exe", "title": "原神"}
    payloads[:] = [piece(9, 2, 8, game)]  # first window 0–10: cut at its end
    idle[:] = [piece(5, 1, 9, {"status": "not-afk"})]
    client.post("/api/sync/activitywatch", json=window(0, 10)).raise_for_status()

    payloads[:] = [piece(9, 5, 9, game)]  # second window 5–15: cut at its start
    idle[:] = [piece(5, 5, 9, {"status": "not-afk"})]
    client.post("/api/sync/activitywatch", json=window(5, 15)).raise_for_status()

    event = next(e for e in client.get("/api/events").json() if e["app"] == "GenshinImpact.exe")
    assert event["start_time"].startswith("2026-09-29T00:02:00")
    assert event["end_time"].startswith("2026-09-29T00:14:00")
    session = next(s for s in client.get("/api/sessions").json() if s["app"] == "GenshinImpact.exe")
    assert session["recorded_seconds"] == 12 * 60
    # The whole session is covered by the rebuilt AFK state, so nothing is left unverified.
    assert session["unverified_seconds"] == 0

    # A third slice inside what is stored changes nothing.
    payloads[:] = [piece(9, 8, 2, game)]
    idle[:] = []
    result = client.post("/api/sync/activitywatch", json=window(8, 10)).json()
    assert result["changed"] == 0


def test_uncropped_revisions_still_replace_the_event(app_context):
    client, _, payloads, _, _ = app_context
    game = {"app": "GenshinImpact.exe", "title": "原神"}
    payloads[:] = [piece(9, 2, 8, game)]
    client.post("/api/sync/activitywatch", json=window(0, 30)).raise_for_status()
    payloads[:] = [piece(9, 2, 3, game)]  # the source itself shortened the event
    client.post("/api/sync/activitywatch", json=window(0, 30)).raise_for_status()
    event = next(e for e in client.get("/api/events").json() if e["app"] == "GenshinImpact.exe")
    assert event["end_time"].startswith("2026-09-29T00:05:00")
