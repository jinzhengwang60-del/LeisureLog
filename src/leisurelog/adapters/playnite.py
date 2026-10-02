"""Read the local SDK export, without opening or changing Playnite's database."""

import json
from pathlib import Path, PureWindowsPath
from uuid import UUID

import yaml

from leisurelog.domain.games import Game

# Shared clients and utilities cannot establish which game is in the foreground.
SHARED = {
    "launcher.exe", "steam.exe", "steamwebhelper.exe", "wegame.exe",
    "leagueclient.exe", "leagueclientux.exe", "riotclientservices.exe",
    "java.exe", "javaw.exe", "plain craft launcher 2.exe", "playnite.desktopapp.exe",
    "obs64.exe", "obs32.exe", "wallpaper64.exe", "wallpaper32.exe",
    "client-win64-shipping.exe",
}


class PlayniteUnavailable(ValueError):
    pass


class PlayniteAdapter:
    def __init__(self, path: Path, bindings_path: Path):
        self.path, self.bindings_path = path, bindings_path

    def fetch(self) -> tuple[dict, list[Game]]:
        try:
            if self.path.stat().st_size > 10_000_000:
                raise ValueError("Export exceeds 10 MB")
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
            bindings = yaml.safe_load(self.bindings_path.read_text(encoding="utf-8")) or {}
            if not isinstance(bindings, dict) or not isinstance(bindings.get("bindings", []), list):
                raise ValueError("Invalid process bindings configuration")
            return payload, parse_export(payload, bindings.get("bindings", []))
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
            raise PlayniteUnavailable(f"Cannot read Playnite export: {exc}") from exc


def parse_export(payload: dict, bindings=()) -> list[Game]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Unsupported Playnite export format")
    rows = payload.get("games")
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("Invalid games list")
    if not isinstance(bindings, (list, tuple)):
        raise ValueError("Invalid process bindings")
    games, ids = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid game")
        if not isinstance(row.get("id"), str):
            raise ValueError("Invalid game ID")
        key = str(UUID(row["id"]))
        name = row["name"]
        if key in ids or not isinstance(name, str) or not name.strip() or len(name) > 300:
            raise ValueError("Duplicate ID or invalid game name")
        ids.add(key)
        if not isinstance(row["installed"], bool):
            raise ValueError("installed must be boolean")
        directory = row.get("directory") or ""
        if not isinstance(directory, str):
            raise ValueError("Invalid directory")
        tags = row.get("tags", [])
        paths = row.get("executables", [])
        if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
            raise ValueError("Invalid tags")
        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
            raise ValueError("Invalid executables")
        matches = set()
        for path in paths:
            app = PureWindowsPath(path).name.casefold()
            if app.endswith(".exe") and app not in SHARED and "crash" not in app:
                matches.add((app, ""))
        for binding in bindings:
            if not isinstance(binding, dict):
                raise ValueError("Invalid process binding")
            if binding.get("name") == name:
                app = binding.get("app")
                title = binding.get("title_contains", "")
                if not isinstance(app, str) or not app.endswith(".exe"):
                    raise ValueError("Process binding requires executable name")
                if not isinstance(title, str):
                    raise ValueError("Invalid process title")
                if app.casefold() in SHARED and not title:
                    raise ValueError("Shared processes require title_contains")
                matches.add((app.casefold(), title))
        games.append(Game(key, name.strip(), row["installed"], directory,
                          tuple(dict.fromkeys(tags)), tuple(sorted(matches))))
    return games
