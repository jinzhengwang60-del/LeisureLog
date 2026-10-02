from dataclasses import replace
from datetime import timedelta

import httpx
import pytest
from alembic import command
from sqlalchemy import select

from leisurelog.adapters.activitywatch import ActivityWatchAdapter
from leisurelog.domain.browser import BrowserEvent, resolve_browser
from leisurelog.domain.models import ActivityEvent
from leisurelog.repositories.models import RawEventRow
from leisurelog.repositories.sqlite import SQLiteRepository
from tests.test_pipeline import START, WINDOW

pytest_plugins = ["tests.test_pipeline"]


def window(app="msedge.exe", device="pc", duration=120):
    return ActivityEvent(
        "window-id",
        "activitywatch",
        "window",
        device,
        START,
        START + timedelta(seconds=duration),
        app,
        "测试页面 - Microsoft Edge",
    )


def page(key="web", start=20, duration=60, url="https://www.bilibili.com/video/BVtest", **kwargs):
    return BrowserEvent(
        key,
        "activitywatch",
        "aw-watcher-web-chrome",
        "pc",
        START + timedelta(seconds=start),
        START + timedelta(seconds=start + duration),
        ("chrome.exe", "msedge.exe"),
        "测试页面",
        url,
        **kwargs,
    )


def total(events):
    return sum((e.end_time - e.start_time).total_seconds() for e in events)


@pytest.mark.parametrize("app", ["msedge.exe", "chrome.exe"])
def test_enrichment_is_partition_not_additional_time(app):
    original = window(app)
    resolved = resolve_browser([original], [page(), page("duplicate")])
    assert total(resolved) == 120
    assert [(e.end_time - e.start_time).total_seconds() for e in resolved] == [20, 60, 40]
    assert resolved[1].url == page().url
    assert resolved[1].browser_event_id == "duplicate"
    assert all(e.window_event_id == original.id for e in resolved)
    assert original.url is None
    assert resolve_browser([], [page()]) == []


@pytest.mark.parametrize(
    "change",
    [
        {"device": "other"},
        {"device": "unknown"},
        {"app": "Weixin.exe"},
        {"title": "其他标签页 - Microsoft Edge"},
    ],
)
def test_unrelated_browser_data_does_not_enrich(change):
    original = replace(window(), **change)
    events = resolve_browser([original], [page()])
    assert len(events) == 1 and events[0].id == original.id and events[0].url is None


def test_conflicting_reports_and_audible_background_are_not_counted():
    events = resolve_browser(
        [window()], [page(), page("other", url="https://example.com", audible=True)]
    )
    assert total(events) == 120 and all(e.url is None for e in events)
    # Adjacent pages with the same title but different URLs partition one foreground window.
    events = resolve_browser(
        [window()],
        [
            page(start=0, duration=60),
            page("second", start=60, duration=60, url="https://live.bilibili.com/1"),
        ],
    )
    assert total(events) == 120 and len(events) == 2 and events[0].url != events[1].url


def source(payloads, hostname="unknown", devices=("pc",), bindings=None):
    buckets = {
        f"window{i}": {"type": "currentwindow", "hostname": device}
        for i, device in enumerate(devices)
    }
    buckets["aw-watcher-web-chrome"] = {"type": "web.tab.current", "hostname": hostname}

    def respond(request):
        if request.url.path == "/api/0/buckets/":
            return httpx.Response(200, json=buckets)
        return httpx.Response(200, json=payloads if "web-chrome" in request.url.path else [])

    client = httpx.Client(base_url="http://aw", transport=httpx.MockTransport(respond))
    return ActivityWatchAdapter(client, bindings), client


def payload(key=1, **data):
    return {
        "id": key,
        "timestamp": START.isoformat(),
        "duration": 120,
        "data": {"title": "测试页面", "url": "https://www.bilibili.com/video/BVtest", **data},
    }


def test_adapter_filters_private_and_internal_pages_and_binds_single_device():
    adapter, client = source(
        [payload(), payload(2, incognito=True), payload(3, url="edge://settings")]
    )
    try:
        records = adapter.fetch(START, START + timedelta(hours=1), None)
        assert len(records) == 1 and records[0].event.device == "pc"
        assert records[0].event.browser_apps == ("chrome.exe", "msedge.exe")
    finally:
        client.close()


def test_unknown_device_is_not_guessed_for_multiple_computers():
    adapter, client = source([payload()], devices=("pc", "laptop"))
    try:
        assert adapter.fetch(START, START + timedelta(hours=1), None)[0].event.device == "unknown"
    finally:
        client.close()
    adapter, client = source(
        [payload()], devices=("pc", "laptop"), bindings={"aw-watcher-web-chrome": "laptop"}
    )
    try:
        assert adapter.fetch(START, START + timedelta(hours=1), None)[0].event.device == "laptop"
    finally:
        client.close()


def add_page(app, event):
    from leisurelog.domain.browser import BrowserSourceRecord

    with app.state.sessions() as db:
        repo = SQLiteRepository(db)
        changed = repo.ingest(BrowserSourceRecord(event, event.id, asdict_payload(event), {}))
        db.commit()
        return changed


def asdict_payload(event):
    return {
        "id": event.id,
        "timestamp": event.start_time.isoformat(),
        "duration": (event.end_time - event.start_time).total_seconds(),
        "data": {"url": event.url, "title": event.title},
    }


def test_persisted_enrichment_manual_priority_website_rule_and_restore(app_context):
    client, app, windows, _, migration = app_context
    windows[:] = [
        {
            "id": 1,
            "timestamp": START.isoformat(),
            "duration": 120,
            "data": {"app": "msedge.exe", "title": "测试页面 - Microsoft Edge"},
        }
    ]
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    original = client.get("/api/events").json()[0]
    assert add_page(app, page(start=0, duration=120))
    assert not add_page(app, page(start=0, duration=120))
    assert client.post("/api/reprocess").json()["events"] == 1
    events = client.get("/api/events").json()
    enriched = events[0]
    assert enriched["classification"]["category"] == "video"
    assert enriched["window_event_id"] == original["id"]
    assert client.get("/api/sessions").json()[0]["recorded_seconds"] == 120
    session = client.get("/api/sessions").json()[0]
    detail = client.get(f"/api/sessions/{session['id']}/details?day=2026-09-29").json()
    assert len(detail["browser_events"]) == 1
    assert detail["window_events"][0]["url"] is None
    assert (
        client.put(
            "/api/events/overrides",
            json={
                "event_ids": [enriched["id"]],
                "category": "reading",
                "content": "自定义",
                "remember_scope": "domain",
            },
        ).status_code
        == 200
    )
    assert client.post("/api/reprocess").status_code == 200
    assert client.get("/api/events").json()[0]["classification"]["origin"] == "manual"
    assert client.delete(f"/api/events/{enriched['id']}/override").status_code == 200
    assert client.get("/api/events").json()[0]["classification"]["origin"] == "learned"
    # Existing window-level corrections remain strongest when URL enrichment arrives.
    assert (
        client.put(f"/api/events/{original['id']}/override", json={"category": "work"}).status_code
        == 200
    )
    assert client.get("/api/events").json()[0]["classification"]["category"] == "work"
    with app.state.sessions() as db:
        assert len(list(db.scalars(select(RawEventRow)))) == 2
    stats = client.get("/api/statistics?start=2026-09-29&end=2026-09-29").json()
    assert stats["totals"]["recorded_seconds"] == 120
    assert client.delete(f"/api/events/{enriched['id']}/override").status_code == 200
    assert client.get("/api/events").json()[0]["classification"]["origin"] == "learned"
    # Resetting an enriched segment does not erase the underlying window correction.
    with app.state.sessions() as db:
        assert SQLiteRepository(db).overrides()[original["id"]].category == "work"
    command.check(migration)
    command.downgrade(migration, "0005")
    command.upgrade(migration, "head")
    assert client.post("/api/reprocess").status_code == 200
    assert client.get("/api/events").json()[0]["classification"]["origin"] == "manual"
    assert client.get("/api/sessions").json()[0]["recorded_seconds"] == 120


def test_browser_status_empty(app_context):
    client, _, _, _, _ = app_context
    data = client.get("/api/browser/status").json()
    assert data["buckets"] == [] and data["matched_segments"] == 0


def test_browser_updates_compaction_protects_current_snapshot(app_context):
    client, app, windows, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    first = page(start=0, duration=120)
    assert add_page(app, first)
    assert add_page(app, replace(first, end_time=first.end_time + timedelta(seconds=30)))
    outcome = client.post("/api/storage/compact")
    assert outcome.status_code == 200, outcome.text
    with app.state.sessions() as db:
        browser = SQLiteRepository(db).browser_events()
        assert len(browser) == 1 and browser[0].end_time == first.end_time + timedelta(seconds=30)
        assert len(list(db.scalars(select(RawEventRow)))) == 3


def test_browser_failure_aborts_whole_import(app_context):
    from leisurelog.adapters.activitywatch import SourceUnavailable

    client, app, _, _, _ = app_context
    adapter, upstream = source([payload(duration_unused=1)])
    original_get = adapter.browser.fetch

    def broken(*args):
        raise ValueError("Broken browser data")

    adapter.browser.fetch = broken
    app.state.source = adapter
    try:
        assert client.post("/api/sync/activitywatch", json=WINDOW).status_code == 502
        assert client.get("/api/events").json() == []
        with pytest.raises(SourceUnavailable):
            adapter.fetch(START, START + timedelta(hours=1), None)
    finally:
        adapter.browser.fetch = original_get
        upstream.close()


def test_browser_rules_use_path_and_safe_domain(app_context):
    _, app, _, _, _ = app_context
    classifier = app.state.pipeline.classifiers[0]
    assert (
        classifier.classify(replace(window(), url="https://manga.bilibili.com/mc1")).category
        == "reading"
    )
    assert (
        classifier.classify(replace(window(), url="https://live.bilibili.com/1")).category == "live"
    )
    assert (
        classifier.classify(replace(window(), url="https://www.bilibili.com/")).category
        == "browsing"
    )
    assert (
        classifier.classify(replace(window(), url="https://www.bilibili.com/video/BV1")).category
        == "video"
    )
    assert (
        classifier.classify(replace(window(), url="https://bilibili.com.evil.example/video/1"))
        is None
    )
    assert classifier.classify(replace(window(), url="http://[broken")) is None
