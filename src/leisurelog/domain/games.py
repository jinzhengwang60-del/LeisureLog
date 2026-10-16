"""Game catalog metadata supplements activity; it never creates playtime."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Game:
    id: str
    name: str
    installed: bool
    directory: str
    tags: tuple[str, ...]
    matches: tuple[tuple[str, str], ...]  # executable basename, optional title substring
