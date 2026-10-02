"""Game catalog metadata supplements activity; it never creates playtime."""

from dataclasses import dataclass

from leisurelog.domain.models import ActivityEvent, Classification


@dataclass(frozen=True)
class Game:
    id: str
    name: str
    installed: bool
    directory: str
    tags: tuple[str, ...]
    matches: tuple[tuple[str, str], ...]  # executable basename, optional title substring


class GameClassifier:
    def __init__(self, games: list[Game]):
        self.matches: dict[str, list[tuple[Game, str]]] = {}
        for game in games:
            if game.installed:
                for app, title in game.matches:
                    self.matches.setdefault(app.casefold(), []).append((game, title))

    def classify(self, event: ActivityEvent) -> Classification | None:
        candidates = {
            game.id: game
            for game, title in self.matches.get(event.app.casefold(), [])
            if not title or title.casefold() in event.title.casefold()
        }
        if len(candidates) != 1:
            return None  # Shared processes need a specific mapping; never guess.
        game = next(iter(candidates.values()))
        return Classification("game", game.name, game.tags, f"playnite:{game.id}")
