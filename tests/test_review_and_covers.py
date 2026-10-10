"""Weekly review figures and Playnite covers for the library wall."""

import json
from datetime import date, timedelta
from pathlib import Path

from leisurelog.adapters.playnite import CoverIndex, PlayniteAdapter, cover_paths
from leisurelog.analytics.review import week_of
from leisurelog.domain.games import Game
from tests.test_pipeline import START, WINDOW
from tests.test_unclassified import add

pytest_plugins = ["tests.test_pipeline"]
GAME_ID = "6289c924-22ba-47ed-8d6b-f845d9659e72"


def test_week_runs_monday_to_sunday():
    assert week_of(date(2026, 10, 10)) == (date(2026, 10, 5), date(2026, 10, 11))
    assert week_of(date(2026, 10, 5)) == (date(2026, 10, 5), date(2026, 10, 11))
    assert week_of(date(2026, 10, 11)) == (date(2026, 10, 5), date(2026, 10, 11))


def test_review_totals_compare_weeks_and_mark_new(app_context):
    client, _, payloads, _, _ = app_context
    add(payloads, 3, 400, "cloudmusic.exe", "Hey Jude", 600)
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    client.post("/api/classification/app-rules", json={
        "source": "activitywatch", "app": "cloudmusic.exe", "category": "music",
        "content": "网易云音乐",
    }).raise_for_status()
    day = (START + timedelta(hours=8)).date()  # the synced activity, as a Beijing date
    data = client.get("/api/review", params={"day": day.isoformat()}).json()
    monday, sunday = week_of(day)
    assert (data["week_start"], data["week_end"]) == (monday.isoformat(), sunday.isoformat())
    assert len(data["days"]) == 7
    music = next(a for a in data["top_activities"] if a["content"] == "网易云音乐")
    assert music["category"] == "music" and music["days"] == 1 and music["new"] is True
    assert data["leisure_by_category"]["music"] == music["active_seconds"]
    assert data["leisure_seconds"] >= music["active_seconds"]
    assert data["previous_leisure_seconds"] == 0
    assert data["busiest_day"]["day"] == day.isoformat()
    # The following week sees the same activity as "last week".
    later = client.get("/api/review", params={"day": (day + timedelta(days=7)).isoformat()}).json()
    assert later["previous_leisure_seconds"] == data["leisure_seconds"]
    assert later["leisure_seconds"] == 0
    assert client.get("/review").status_code == 200


def write_export(tmp_path: Path, cover: str, extra=()) -> Path:
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"schema_version": 1, "games": [
        {"id": GAME_ID, "name": "Left 4 Dead 2", "installed": True, "directory": "",
         "tags": [], "executables": [r"C:\Games\L4D2\left4dead2.exe"], "cover": cover},
        *extra,
    ]}), encoding="utf-8")
    return export


def test_cover_paths_only_accept_images_in_the_games_own_folder(tmp_path):
    good = tmp_path / GAME_ID / "cover.jpg"
    other = "1f0e4a2c-0000-4000-8000-000000000001"
    rows = [
        {"id": GAME_ID, "cover": str(good)},
        {"id": other, "cover": str(tmp_path / "elsewhere" / "x.jpg")},
        {"id": other, "cover": str(tmp_path / other / "x.exe")},
        {"id": other, "cover": other + r"\cover.jpg"},
        {"id": "not-a-uuid", "cover": str(tmp_path / "not-a-uuid" / "c.jpg")},
    ]
    assert cover_paths({"games": rows}) == {GAME_ID: good}
    assert cover_paths(None) == {}


def game(key, name, apps=()):
    return Game(key, name, True, "", (), tuple((a, "") for a in apps))


def test_cover_index_matches_by_name_then_program_then_containment(tmp_path):
    a, b, c = (f"00000000-0000-4000-8000-00000000000{i}" for i in (1, 2, 3))
    index = CoverIndex(
        (game(a, "棕色塵埃2", ["browndust ii.exe"]), game(b, "潜水员戴夫 DAVE THE DIVER"),
         game(c, "原神", ["yuanshen.exe"])),
        {a: tmp_path / "a.jpg", b: tmp_path / "b.jpg"},
    )
    assert index.game_for("原神").id == c and index.cover_for("原神") is None  # no cover
    assert index.cover_for("棕色尘埃2", ["BrownDust II.exe"]) == (a, tmp_path / "a.jpg")
    assert index.cover_for("潜水员戴夫", ["DaveTheDiver.exe"]) == (b, tmp_path / "b.jpg")
    assert index.game_for("完全不同", ["other.exe"]) is None
    platform = CoverIndex((game(a, "英雄联盟WeGame版"),), {a: tmp_path / "a.jpg"})
    assert platform.game_for("WeGame", ["wegame.exe"]) is None  # inside, not at the start
    assert platform.game_for("英雄联盟", ["LeagueAkari.exe"]).id == a
    twins = CoverIndex((game(a, "Dave"), game(b, "Dave")), {a: tmp_path / "a.jpg"})
    assert twins.game_for("Dave") is None  # ambiguous names never guess


def test_cover_endpoint_serves_the_file_and_listing_links_it(app_context, tmp_path):
    client, app, _, _, _ = app_context
    image = tmp_path / GAME_ID / "cover.jpg"
    image.parent.mkdir()
    image.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    bindings = tmp_path / "bindings.yaml"
    bindings.write_text("bindings: []\n", encoding="utf-8")
    app.state.playnite = PlayniteAdapter(write_export(tmp_path, str(image)), bindings)
    response = client.get("/api/library/cover", params={"game": GAME_ID})
    assert response.status_code == 200
    assert response.content == image.read_bytes()
    assert client.get("/api/library/cover", params={"game": "nope"}).status_code == 404
    image.unlink()
    assert client.get("/api/library/cover", params={"game": GAME_ID}).status_code == 404
    listing = client.get("/api/library").json()
    assert all("cover" in item for item in listing["items"])
