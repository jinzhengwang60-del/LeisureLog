from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from sqlalchemy import select

from leisurelog.domain.browser import ResolvedActivity, resolve_browser
from leisurelog.domain.daily import daily_activity
from leisurelog.domain.idle import apply_idle
from leisurelog.domain.models import IdleEvent
from leisurelog.domain.sessionization import merge_sessions
from leisurelog.domain.timing import TimingRule, resolve_timing
from leisurelog.repositories.models import TimingOverrideRow
from leisurelog.repositories.sqlite import SQLiteRepository
from tests.test_browser import page, window
from tests.test_pipeline import START, WINDOW

pytest_plugins = ["tests.test_pipeline"]


@pytest.mark.parametrize(
    "policy,audible,active,retained",
    [
        ("afk", False, 0, 0),
        ("foreground", False, 120, 120),
        ("audible", False, 0, 0),
        ("audible", True, 120, 120),
    ],
)
def test_explicit_policy_and_detected_afk(policy, audible, active, retained):
    original = window()
    event = ResolvedActivity(
        **original.__dict__, window_event_id=original.id, timing_policy=policy, audible=audible
    )
    states = [
        IdleEvent(
            "away", "activitywatch", "afk", "pc", START, START + timedelta(seconds=120), "afk"
        )
    ]
    sessions = merge_sessions([event], 60)
    apply_idle(sessions, [event], states)
    assert sessions[0].active_seconds == active
    assert sessions[0].detected_afk_seconds == 120
    assert sessions[0].retained_afk_seconds == retained
    assert sessions[0].afk_seconds == 120 - retained
    daily = daily_activity(sessions, [event], states)[0]
    assert daily.active_seconds == active and daily.retained_afk_seconds == retained


def test_only_matched_audible_foreground_interval_is_retained():
    original = window()
    pages = [page(start=30, duration=60, audible=True)]
    events = [replace(e, timing_policy="audible") for e in resolve_browser([original], pages)]
    idle = [
        IdleEvent(
            "away", "activitywatch", "afk", "pc", START, START + timedelta(seconds=120), "afk"
        )
    ]
    sessions = merge_sessions(events, 60)
    apply_idle(sessions, events, idle)
    assert sum(s.recorded_seconds for s in sessions) == 120
    assert sum(s.active_seconds for s in sessions) == 60
    assert sum(s.detected_afk_seconds for s in sessions) == 120
    assert sum(s.retained_afk_seconds for s in sessions) == 60
    assert resolve_browser([], pages) == []


def test_unknown_coverage_and_merge_gap_remain_unverified_and_uncounted():
    original = window()
    first = ResolvedActivity(
        **original.__dict__, window_event_id=original.id, timing_policy="foreground"
    )
    second = replace(
        first,
        id="second",
        start_time=START + timedelta(seconds=150),
        end_time=START + timedelta(seconds=180),
    )
    sessions = merge_sessions([first, second], 60)
    apply_idle(sessions, [first, second], [])
    assert len(sessions) == 1 and sessions[0].active_seconds == 150
    assert sessions[0].unverified_seconds == 150
    assert sessions[0].detected_afk_seconds == 0
    different = replace(second, timing_policy="afk")
    assert len(merge_sessions([first, different], 60)) == 2


def test_timing_rule_match_and_manual_precedence():
    event = resolve_browser([window()], [])[0]
    rules = [
        TimingRule("reading", "foreground", category="reading"),
        TimingRule("edge", "audible", app="MSEDGE.EXE"),
    ]
    assert resolve_timing(event, {}, rules) == ("audible", "rule:edge")
    assert resolve_timing(event, {event.id: "foreground"}, rules) == ("foreground", "manual")
    assert resolve_timing(event, {event.id: "default"}, rules) == ("audible", "rule:edge")


def test_cross_midnight_save_restore_and_statistics_consistent(app_context):
    client, app, payloads, _, migration = app_context
    start = datetime(2026, 9, 29, 15, 59, tzinfo=timezone.utc)
    payloads[:] = [{**payloads[0], "timestamp": start.isoformat(), "duration": 180}]
    app.state.test_idle_payloads[:] = [
        {"id": 1, "timestamp": start.isoformat(), "duration": 180, "data": {"status": "afk"}}
    ]
    interval = {"start": start.isoformat(), "end": (start + timedelta(minutes=5)).isoformat()}
    client.post("/api/sync/activitywatch", json=interval).raise_for_status()
    key = client.get("/api/events").json()[0]["id"]
    assert client.get("/api/sessions").json()[0]["active_seconds"] == 0
    client.put(
        "/api/events/timing", json={"event_ids": [key], "policy": "foreground"}
    ).raise_for_status()
    client.post("/api/reprocess").raise_for_status()
    session = client.get("/api/sessions").json()[0]
    assert session["active_seconds"] == 180 and session["timing_origin"] == "manual"
    assert session["detected_afk_seconds"] == session["retained_afk_seconds"] == 180
    result = client.get("/api/statistics?start=2026-09-29&end=2026-09-30").json()
    assert result["totals"]["active_seconds"] == 180
    assert [r["retained_afk_seconds"] for r in result["trend"]] == [60, 120]
    for day, expected in [("2026-09-29", 60), ("2026-09-30", 120)]:
        data = client.get(f"/api/dashboard?day={day}").json()
        assert data["summary"]["retained_afk_seconds"] == expected
    command.check(migration)
    backup = client.post("/api/storage/backups").json()
    assert backup["verified"] and backup["counts"]["timing_overrides"] == 1
    client.put("/api/events/timing", json={"event_ids": [key], "policy": None}).raise_for_status()
    assert client.get("/api/sessions").json()[0]["active_seconds"] == 0
    assert client.get("/api/events").json()[0]["timing_origin"] == "default"
    client.put(
        "/api/events/timing", json={"event_ids": [key], "policy": "foreground"}
    ).raise_for_status()
    command.downgrade(migration, "0006")
    command.upgrade(migration, "head")
    client.post("/api/reprocess").raise_for_status()
    assert client.get("/api/sessions").json()[0]["active_seconds"] == 0


def test_invalid_selection_and_write_failure_roll_back(app_context, monkeypatch):
    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    key = client.get("/api/events").json()[0]["id"]
    assert (
        client.put(
            "/api/events/timing", json={"event_ids": [key, "missing"], "policy": "foreground"}
        ).status_code
        == 404
    )
    assert (
        client.put("/api/events/timing", json={"event_ids": [key], "policy": "bad"}).status_code
        == 422
    )

    def fail(*args):
        raise RuntimeError("daily write failed")

    monkeypatch.setattr(SQLiteRepository, "replace_daily", fail)
    with pytest.raises(RuntimeError, match="daily write failed"):
        client.put("/api/events/timing", json={"event_ids": [key], "policy": "foreground"})
    with app.state.sessions() as db:
        assert list(db.scalars(select(TimingOverrideRow))) == []


def test_configured_policy_manual_override_restore_and_reclassification(app_context):
    client, app, _, _, _ = app_context
    app.state.pipeline.timing_rules = [TimingRule("game-foreground", "foreground", category="game")]
    app.state.test_idle_payloads[:] = [
        {"id": 1, "timestamp": START.isoformat(), "duration": 180, "data": {"status": "afk"}}
    ]
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    events = client.get("/api/events").json()
    key = events[0]["id"]
    assert client.get("/api/sessions").json()[0]["active_seconds"] == 120
    client.put("/api/events/timing", json={"event_ids": [key], "policy": "afk"}).raise_for_status()
    assert sum(s["active_seconds"] for s in client.get("/api/sessions").json()) == 60
    client.put("/api/events/timing", json={"event_ids": [key], "policy": None}).raise_for_status()
    assert sum(s["active_seconds"] for s in client.get("/api/sessions").json()) == 120
    client.put(f"/api/events/{key}/override", json={"category": "work"}).raise_for_status()
    assert sum(s["active_seconds"] for s in client.get("/api/sessions").json()) == 60


def test_timing_choice_survives_browser_enrichment_and_segment_reset(app_context):
    from tests.test_browser import add_page

    client, app, payloads, _, _ = app_context
    payloads[:] = [
        {
            **payloads[0],
            "duration": 120,
            "data": {"app": "msedge.exe", "title": "测试页面 - Microsoft Edge"},
        }
    ]
    app.state.test_idle_payloads[:] = [
        {"id": 1, "timestamp": START.isoformat(), "duration": 120, "data": {"status": "afk"}}
    ]
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    original = client.get("/api/events").json()[0]["id"]
    client.put(
        "/api/events/timing", json={"event_ids": [original], "policy": "foreground"}
    ).raise_for_status()
    add_page(app, page(start=0, duration=120))
    client.post("/api/reprocess").raise_for_status()
    derived = client.get("/api/events").json()[0]
    assert derived["id"] != original and derived["timing_policy"] == "foreground"
    client.put(
        "/api/events/timing", json={"event_ids": [derived["id"]], "policy": None}
    ).raise_for_status()
    assert client.get("/api/sessions").json()[0]["active_seconds"] == 0
    with app.state.sessions() as db:
        assert SQLiteRepository(db).timing_overrides()[original] == "foreground"
