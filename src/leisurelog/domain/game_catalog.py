"""Narrow immutable game metadata contracts; no activity or playtime import."""

import json
import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from leisurelog.domain.games import Game
from leisurelog.domain.models import ActivityEvent


class GameCatalogUnavailable(ValueError):
    """A missing or invalid local export; a later explicit/scheduled read may recover."""


def _text(value, maximum, *, empty=True):
    if type(value) is not str or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError("游戏资料字段无效或超出大小限制")


def _games(values):
    if type(values) is not tuple or len(values) > 10000:
        raise ValueError("游戏资料需要有上限的不可变集合")
    ids = set()
    for game in values:
        if type(game) is not Game or type(game.installed) is not bool:
            raise ValueError("游戏资料类型无效")
        if type(game.id) is not str or str(UUID(game.id)) != game.id or game.id in ids:
            raise ValueError("游戏 ID 无效或重复")
        ids.add(game.id)
        _text(game.name, 300, empty=False)
        _text(game.directory, 4096)
        if type(game.tags) is not tuple or len(game.tags) > 100:
            raise ValueError("游戏标签必须为有上限的不可变集合")
        for tag in game.tags:
            _text(tag, 300)
        if type(game.matches) is not tuple or len(game.matches) > 100:
            raise ValueError("进程匹配必须为有上限的不可变集合")
        for match in game.matches:
            if type(match) is not tuple or len(match) != 2:
                raise ValueError("进程匹配字段无效")
            _text(match[0], 300, empty=False)
            _text(match[1], 2000)


@dataclass(frozen=True)
class GameCatalogFiles:
    export_json: str
    bindings_yaml: str

    def __post_init__(self):
        _text(self.export_json, 10_000_000)
        _text(self.bindings_yaml, 1_000_000)


class GameCatalogFilesReader(Protocol):
    def read(self) -> GameCatalogFiles: ...


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("游戏导出含重复 JSON 字段")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("游戏快照不能包含 NaN 或无穷值")


@dataclass(frozen=True)
class GameCatalogImport:
    raw_json: str
    games: tuple[Game, ...]

    def __post_init__(self):
        _text(self.raw_json, 10_000_000, empty=False)
        _games(self.games)
        # Source-specific schema/identity correspondence belongs at the source boundary.
        if type(self.payload()) is not dict:
            raise ValueError("资料原始快照需要 JSON 对象")

    def payload(self) -> dict:
        return json.loads(
            self.raw_json, object_pairs_hook=_unique, parse_constant=_invalid_constant
        )


@dataclass(frozen=True)
class GameCatalogSnapshot:
    revision: str = "empty"
    games: tuple[Game, ...] = ()
    namespace: str = "game"

    def __post_init__(self):
        _text(self.revision, 100, empty=False)
        _games(self.games)
        if type(self.namespace) is not str or not re.fullmatch(
            r"[a-z][a-z0-9-]{0,63}", self.namespace
        ):
            raise ValueError("资料身份需要明确的宿主命名空间")


class GameCatalogReader(Protocol):
    def read(self) -> GameCatalogSnapshot: ...


class GameCatalogSource(Protocol):
    def fetch(self) -> GameCatalogImport: ...


@dataclass(frozen=True)
class GameMatch:
    game_id: str

    def __post_init__(self):
        if type(self.game_id) is not str or str(UUID(self.game_id)) != self.game_id:
            raise ValueError("游戏匹配需要有效的游戏 ID")


class GameCatalogClassifier(Protocol):
    def classify(self, event: ActivityEvent, catalog: GameCatalogSnapshot) -> GameMatch | None: ...
