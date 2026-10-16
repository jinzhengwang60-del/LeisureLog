import json
from dataclasses import replace
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from leisurelog.repositories.games import SQLiteGameCatalog
from leisurelog.repositories.models import GameSnapshotRow, RawEventRow
from leisurelog.runtime import AutomaticSync
from leisurelog_plugins.playnite import (
    GameClassifier,
    PlayniteAdapter,
    PlayniteUnavailable,
    parse_export,
)
from tests.test_pipeline import WINDOW, event

pytest_plugins = ["tests.test_pipeline"]


def catalog(*rows):
    return {"schema_version": 1, "exported_at": "2026-10-02T00:00:00Z", "games": list(rows)}


def game(name="原神", path=r"D:\Genshin Impact Game\YuanShen.exe", installed=True):
    return {"id": str(uuid4()), "name": name, "installed": installed,
            "directory": r"D:\Game", "tags": ["RPG"], "executables": [path]}


def test_matching_shared_processes_conflicts_and_install_status():
    direct = game()
    matcher = GameClassifier(parse_export(catalog(direct)))
    assert matcher.classify(event("one", 0, 60, "YUANSHEN.EXE")).content == "原神"
    assert matcher.classify(event("one", 0, 60, "launcher.exe")) is None
    duplicate = {**direct, "id": str(uuid4()), "name": "另一个游戏"}
    assert GameClassifier(parse_export(catalog(direct, duplicate))).classify(
        event("one", 0, 60, "YuanShen.exe")
    ) is None
    assert GameClassifier(parse_export(catalog({**direct, "installed": False}))).classify(
        event("one", 0, 60, "YuanShen.exe")
    ) is None
    minecraft = game("Minecraft（PCL）", r"D:\PCL\Plain Craft Launcher 2.exe")
    binding = {"name": minecraft["name"], "app": "javaw.exe", "title_contains": "Minecraft"}
    matcher = GameClassifier(parse_export(catalog(minecraft), [binding]))
    assert matcher.classify(event("java", 0, 60, "javaw.exe")) is None
    assert matcher.classify(replace(event("java", 0, 60, "javaw.exe"),
                                    title="Minecraft 1.21")).content == "Minecraft（PCL）"
    assert matcher.classify(event("pcl", 0, 60, "Plain Craft Launcher 2.exe")) is None
    with pytest.raises(ValueError, match="title_contains"):
        parse_export(catalog(minecraft), [{"name": minecraft["name"], "app": "javaw.exe"}])


@pytest.mark.parametrize("payload", [
    {"schema_version": 9, "games": []},
    catalog({**game(), "installed": "true"}),
    catalog({**game(), "tags": [None]}),
    catalog({**game(), "id": 123}),
])
def test_bad_export_rejected(payload):
    with pytest.raises((ValueError, TypeError)):
        parse_export(payload)


def test_generic_shipping_process_requires_specific_game_title():
    row = game("鸣潮", r"D:\Game\Client-Win64-Shipping.exe")
    assert parse_export(catalog(row))[0].matches == ()
    with pytest.raises(ValueError, match="title_contains"):
        parse_export(catalog(row), [{"name": "鸣潮", "app": "Client-Win64-Shipping.exe"}])
    bindings = [
        {"name": "鸣潮", "app": "Client-Win64-Shipping.exe", "title_contains": title}
        for title in ("Wuthering Waves", "鸣潮")
    ]
    classifier = GameClassifier(parse_export(catalog(row), bindings))
    generic = event("generic", 0, 60, "Client-Win64-Shipping.exe")
    for title in ("", "Another Unreal Game"):
        assert classifier.classify(replace(generic, title=title)) is None
    for title in ("Wuthering Waves", "鸣潮", "Wuthering Waves 鸣潮"):
        assert classifier.classify(replace(generic, title=title)).content == "鸣潮"


def test_adapter_missing_invalid_and_bom(tmp_path):
    path, bindings = tmp_path / "catalog.json", tmp_path / "bindings.yaml"
    adapter = PlayniteAdapter(path, bindings)
    with pytest.raises(PlayniteUnavailable):
        adapter.fetch()
    bindings.write_text("bindings: []", encoding="utf-8")
    path.write_text(json.dumps(catalog(game()), ensure_ascii=False), encoding="utf-8-sig")
    assert adapter.fetch()[1][0].name == "原神"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(PlayniteUnavailable):
        adapter.fetch()
    path.write_text(json.dumps(catalog(game())), encoding="utf-8")
    bindings.write_text("- invalid", encoding="utf-8")
    with pytest.raises(PlayniteUnavailable):
        adapter.fetch()


def test_import_rebuild_idempotence_failure_and_manual_priority(app_context, tmp_path):
    client, app, payloads, _, _ = app_context
    payloads[:] = [{**payloads[0], "data": {"app": "YuanShen.exe", "title": "原神"}}]
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    assert client.get("/api/events").json()[0]["classification"]["category"] == "unknown"
    path = app.state.settings.playnite_export_path
    bindings = app.state.settings.playnite_bindings_path
    row = game()
    payload = catalog(row)
    path.write_text(json.dumps(payload), encoding="utf-8")
    bindings.write_text("bindings: []", encoding="utf-8")
    result = client.post("/api/games/playnite/import")
    assert result.status_code == 200, result.text
    assert result.json()["recognizable"] == 1
    current = client.get("/api/events").json()[0]
    assert current["classification"]["content"] == "原神"
    assert current["classification"]["origin"].startswith("playnite:")
    assert client.get("/api/sessions").json()[0]["recorded_seconds"] == 60
    payload["exported_at"] = "2026-10-03T00:00:00Z"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert client.post("/api/games/playnite/import").json()["changed"] is False
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(GameSnapshotRow)) == 1
        assert db.scalar(select(func.count()).select_from(RawEventRow)) == 1
    client.put(f"/api/events/{current['id']}/override", json={"category": "work"})
    payload["games"][0]["name"] = "新的游戏名称"
    path.write_text(json.dumps(payload), encoding="utf-8")
    client.post("/api/games/playnite/import").raise_for_status()
    assert client.get("/api/events").json()[0]["classification"]["category"] == "work"
    path.write_text("broken", encoding="utf-8")
    assert client.post("/api/games/playnite/import").status_code == 422
    assert client.get("/api/games/playnite").json()["total"] == 1
    client.delete(f"/api/events/{current['id']}/override").raise_for_status()
    assert client.get("/api/events").json()[0]["classification"]["content"] == "新的游戏名称"
    # Catalog is reconstructed from a fresh DB session, not an in-memory singleton.
    with app.state.sessions() as db:
        assert SQLiteGameCatalog(db).games()[0].name == "新的游戏名称"


def test_scheduled_import_no_phantom_activity_and_missing_export(app_context, tmp_path):
    client, app, _, _, _ = app_context
    path = app.state.settings.playnite_export_path
    bindings = app.state.settings.playnite_bindings_path
    path.write_text(json.dumps(catalog(game())), encoding="utf-8")
    bindings.write_text("bindings: []", encoding="utf-8")
    class EmptySource:
        def fetch(self, *args):
            return []
    sync = AutomaticSync(app.state.sessions, EmptySource(), app.state.pipeline,
                         app.state.settings, app.state.game_catalog.refresh)
    sync(Event())
    assert client.get("/api/games/playnite").json()["total"] == 1
    assert client.get("/api/events").json() == []
    assert client.get("/api/sessions").json() == []
    path.unlink()
    sync(Event())
    assert client.get("/api/games/playnite").json()["total"] == 1


def test_learned_rule_and_yaml_priority(app_context, tmp_path):
    client, app, _, _, _ = app_context
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    row = game("Playnite 名称", r"D:\Game\GenshinImpact.exe")
    with app.state.sessions() as db:
        SQLiteGameCatalog(db).replace(catalog(row), parse_export(catalog(row)))
        db.commit()
    client.post("/api/reprocess").raise_for_status()
    current = client.get("/api/events").json()[0]
    assert current["classification"]["content"] == "原神"  # Existing YAML rule wins.
    client.put("/api/events/overrides", json={"event_ids": [current["id"]],
                                             "category": "work", "remember_scope": "app"})
    client.delete(f"/api/events/{current['id']}/override").raise_for_status()
    assert client.get("/api/events").json()[0]["classification"]["origin"] == "learned"
