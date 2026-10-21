"""A broken historical manifest must not disable future backups or delete old files."""

import json
from datetime import datetime, timedelta, timezone

import pytest

pytest_plugins = ["tests.test_pipeline"]


@pytest.mark.parametrize("broken", [
    None, [], {}, {"created_at": "bad"},
    {"created_at": "2026-01-01", "verification": {}},
    {"created_at": "2026-01-01T00:00:00+00:00", "verification": {"verified": True}},
])
def test_invalid_metadata_does_not_break_storage_or_rotation(app_context, broken):
    client, app, _, _, _ = app_context
    backup = client.post("/api/storage/backups").json()
    store = app.state.storage.store
    path = store.directory / backup["name"]
    manifest = path.with_suffix(".json")
    manifest.write_text(json.dumps(broken), encoding="utf-8")
    original = path.read_bytes()
    overview = client.get("/api/storage")
    assert overview.status_code == 200
    assert overview.json()["backups"] == []
    assert overview.json()["invalid_backups"] == [backup["name"]]
    # Invalid files neither suppress new backups nor enter automatic deletion.
    now = datetime.now(timezone.utc) + timedelta(days=8)
    assert app.state.storage.backup_if_due(7, 1, now=now) is not None
    assert path.read_bytes() == original and manifest.exists()
    assert len(client.get("/api/storage").json()["backups"]) == 1


def test_backup_counts_and_timezone_are_validated_before_retention(app_context):
    client, app, _, _, _ = app_context
    backup = client.post("/api/storage/backups").json()
    path = (app.state.storage.store.directory / backup["name"]).with_suffix(".json")
    original = json.loads(path.read_text(encoding="utf-8"))
    for update in ({"created_at": "2026-01-01T00:00:00"}, {"automatic": "yes"}):
        path.write_text(json.dumps({**original, **update}), encoding="utf-8")
        assert client.get("/api/storage").json()["invalid_backups"] == [backup["name"]]
    original["verification"]["tables"]["raw_events"]["count"] = -1
    path.write_text(json.dumps(original), encoding="utf-8")
    assert client.get("/api/storage").json()["backups"] == []
