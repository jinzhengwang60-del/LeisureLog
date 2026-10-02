import sqlite3

from leisurelog.repositories.storage import connect_readonly, fingerprint
from tests.test_pipeline import WINDOW

pytest_plugins = ["tests.test_pipeline"]


def revisions(client, payloads):
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    for duration in [70, 80, 90]:
        payloads[0]["duration"] = duration
        client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()


def test_compact_preserves_all_business_data_latest_raw_and_verified_backup(app_context):
    client, app, payloads, _, _ = app_context
    revisions(client, payloads)
    event_id = client.get("/api/events").json()[0]["id"]
    client.put(
        "/api/events/overrides",
        json={
            "event_ids": [event_id],
            "category": "work",
            "remember_scope": "app",
        },
    ).raise_for_status()
    store = app.state.storage.store
    with connect_readonly(store.database) as db:
        before = fingerprint(db)
        latest = db.execute("SELECT id,raw_event_id FROM activity_events ORDER BY id").fetchall()
    assert client.get("/api/storage").json()["superseded_snapshots"] == 3
    response = client.post("/api/storage/compact")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["deleted_snapshots"] == 3
    assert result["backup"]["verified"]
    assert result["vacuum_completed"]
    with connect_readonly(store.download_path(result["backup"]["name"])) as db:
        assert fingerprint(db) == before
    with connect_readonly(store.database) as db:
        after = fingerprint(db)
        assert (
            db.execute("SELECT id,raw_event_id FROM activity_events ORDER BY id").fetchall()
            == latest
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert after["raw_events"]["count"] == 2
    assert {k: v for k, v in before.items() if k != "raw_events"} == {
        k: v for k, v in after.items() if k != "raw_events"
    }
    again = client.post("/api/storage/compact").json()
    assert again["deleted_snapshots"] == 0 and again["backup"] is None
    assert len(client.get("/api/storage").json()["backups"]) == 1
    # Source can later revert to a removed revision; ingestion recreates its raw snapshot.
    payloads[0]["duration"] = 70
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    assert client.get("/api/events").json()[0]["classification"]["origin"] == "manual"


def test_failed_backup_and_failed_delete_do_not_change_data(app_context, monkeypatch):
    client, app, payloads, _, _ = app_context
    revisions(client, payloads)
    store = app.state.storage.store
    with connect_readonly(store.database) as db:
        before = fingerprint(db)

    def fail():
        raise ValueError("backup failed")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_create_backup", fail)
        assert client.post("/api/storage/compact").status_code == 503
    with sqlite3.connect(store.database) as db:
        db.execute(
            "CREATE TRIGGER block_compaction BEFORE DELETE ON raw_events "
            "BEGIN SELECT RAISE(ABORT, 'simulated deletion failure'); END"
        )
    assert client.post("/api/storage/compact").status_code == 503
    with connect_readonly(store.database) as db:
        assert fingerprint(db) == before
    with sqlite3.connect(store.database) as db:
        db.execute("DROP TRIGGER block_compaction")
    assert client.post("/api/storage/compact").status_code == 200


def test_revisions_after_backup_are_not_removed(app_context, monkeypatch):
    client, app, payloads, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    payloads[0]["duration"] = 70
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    store = app.state.storage.store
    original = store._create_backup

    def backup_then_sync():
        result = original()
        payloads[0]["duration"] = 80
        client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
        return result

    monkeypatch.setattr(store, "_create_backup", backup_then_sync)
    result = client.post("/api/storage/compact").json()
    assert result["deleted_snapshots"] == 1
    assert client.get("/api/storage").json()["superseded_snapshots"] == 1
    assert client.get("/api/storage").json()["counts"]["raw_events"] == 3


def test_idle_old_versions_compacted_but_orphans_retained(app_context):
    client, app, _, _, _ = app_context
    idle = app.state.test_idle_payloads
    idle.append({"id": 8, "timestamp": WINDOW["start"], "duration": 10, "data": {"status": "afk"}})
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    idle[0]["duration"] = 20
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    with sqlite3.connect(app.state.storage.store.database) as db:
        db.execute(
            "INSERT INTO raw_events (event_id,source,stream,source_event_id,payload_hash,"
            "payload,source_metadata,received_at) VALUES "
            "('orphan','test','test','x','hash','{}','{}','2026-09-30')"
        )
    result = client.post("/api/storage/compact").json()
    assert result["deleted_snapshots"] == 1
    assert client.get("/api/idle-events").json()[0]["status"] == "afk"
    with connect_readonly(app.state.storage.store.database) as db:
        assert (
            db.execute("SELECT count(*) FROM raw_events WHERE event_id='orphan'").fetchone()[0] == 1
        )
