from leisurelog.domain.game_types import validate_choice
from leisurelog.domain.ports import GamePreferencesStore


class GameTypeService:
    def __init__(self, store: GamePreferencesStore):
        self.store = store

    def save(self, key, primary, tags):
        tags = validate_choice(primary, tags)
        if not self.store.exists(key):
            raise KeyError(key)
        self.store.save_type(key, primary, tags)

    def reset(self, key):
        if not self.store.exists(key):
            raise KeyError(key)
        self.store.remove_type(key)
