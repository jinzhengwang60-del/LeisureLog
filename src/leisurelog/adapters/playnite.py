"""Read the local SDK export, without opening or changing Playnite's database."""

import json
from dataclasses import dataclass, field
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


COVER_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def cover_paths(payload) -> dict[str, Path]:
    """Playnite game ID -> local cover image. Playnite keeps a game's images in a folder named
    after the game ID; anything else, or any non-image path, is ignored."""
    covers: dict[str, Path] = {}
    games = payload.get("games") if isinstance(payload, dict) else None
    for row in games if isinstance(games, list) else []:
        if not isinstance(row, dict):
            continue
        cover, key = row.get("cover"), row.get("id")
        if not all(isinstance(v, str) and v.strip() for v in (cover, key)):
            continue
        try:
            key = str(UUID(key))
        except ValueError:
            continue
        path = Path(PureWindowsPath(cover))
        if not path.is_absolute() or path.suffix.casefold() not in COVER_TYPES:
            continue
        if path.parent.name.casefold() != key:
            continue
        covers[key] = path
    return covers


@dataclass(frozen=True)
class CoverIndex:
    games: tuple[Game, ...] = ()
    covers: dict[str, Path] = field(default_factory=dict)

    def game_for(self, name: str, apps=()) -> Game | None:
        """The Playnite game a library item is about: the same name, then a shared program
        file, then one name starting with the other ("潜水员戴夫" / "潜水员戴夫 DAVE THE DIVER";
        a name merely inside another, like a platform in a game's title, does not count).
        A step that finds two games stops the search."""
        wanted = name.strip().casefold()
        programs = {app.casefold() for app in apps}

        def same_name(game):
            return game.name.strip().casefold() == wanted

        def same_program(game):
            return bool(programs & {app.casefold() for app, _ in game.matches})

        def prefix(game):
            other = game.name.strip().casefold()
            shorter = min(len(wanted), len(other))
            return shorter >= 2 and (other.startswith(wanted) or wanted.startswith(other))

        for test in (same_name, same_program, prefix):
            found = {game.id: game for game in self.games if test(game)}
            if len(found) > 1:
                return None
            if found:
                return next(iter(found.values()))
        return None

    def cover_for(self, name: str, apps=()) -> tuple[str, Path] | None:
        game = self.game_for(name, apps)
        path = self.covers.get(game.id) if game else None
        return (game.id, path) if path else None


class PlayniteAdapter:
    def __init__(self, path: Path, bindings_path: Path):
        self.path, self.bindings_path = path, bindings_path
        self._covers: tuple[tuple[int, int], CoverIndex] | None = None

    def covers(self) -> CoverIndex:
        """Cover lookup from the latest export and process bindings, re-read when either changes."""
        try:
            stamp = (self.path.stat().st_mtime_ns, self.bindings_path.stat().st_mtime_ns)
        except OSError:
            return CoverIndex()
        if self._covers is None or self._covers[0] != stamp:
            try:
                payload, games = self.fetch()
                index = CoverIndex(tuple(games), cover_paths(payload))
            except PlayniteUnavailable:
                index = CoverIndex()
            self._covers = (stamp, index)
        return self._covers[1]

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
