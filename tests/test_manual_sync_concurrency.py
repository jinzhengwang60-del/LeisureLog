"""A slow source must not hold the single SQLite writer hostage."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from tests.test_pipeline import WINDOW

pytest_plugins = ["tests.test_pipeline"]


def test_manual_sync_waits_without_blocking_corrections(app_context, monkeypatch):
    client, app, payloads, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    key = client.get("/api/events").json()[0]["id"]
    original_fetch = app.state.source.fetch
    entered, release = Event(), Event()

    def slow_fetch(*args):
        entered.set()
        assert release.wait(10)
        return original_fetch(*args)

    monkeypatch.setattr(app.state.source, "fetch", slow_fetch)
    payloads[0]["duration"] = 70
    with ThreadPoolExecutor(max_workers=2) as executor:
        sync = executor.submit(client.post, "/api/sync/activitywatch", json=WINDOW)
        try:
            assert entered.wait(3)
            correction = executor.submit(
                client.put, f"/api/events/{key}/override", json={"category": "work"},
            )
            correction.result(timeout=3).raise_for_status()
        finally:
            release.set()
        assert sync.result(timeout=10).json()["changed"] == 1
    saved = next(e for e in client.get("/api/events").json() if e["id"] == key)
    assert saved["classification"]["origin"] == "manual"
    assert saved["classification"]["category"] == "work"
