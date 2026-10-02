from leisurelog.domain.storage import StorageStore


class StorageService:
    def __init__(self, store: StorageStore):
        self.store = store

    def overview(self) -> dict:
        return {**self.store.info(), "backups": self.store.backups()}

    def backup(self) -> dict:
        return self.store.create_backup()

    def compact(self) -> dict:
        return self.store.compact()
