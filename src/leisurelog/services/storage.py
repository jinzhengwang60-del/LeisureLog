from datetime import datetime, timedelta, timezone

from leisurelog.domain.storage import BackupBusy, StorageStore


class StorageService:
    def __init__(self, store: StorageStore):
        self.store = store

    def overview(self) -> dict:
        return {**self.store.info(), "backups": self.store.backups()}

    def backup(self) -> dict:
        return self.store.create_backup()

    def backup_if_due(self, every_days: int, keep: int, now: datetime | None = None):
        """Make an automatic backup when the newest backup of any kind is ``every_days`` old,
        then keep only the newest ``keep`` automatic ones. Manual backups are never removed."""
        if every_days <= 0:
            return None
        now = now or datetime.now(timezone.utc)
        newest = max(
            (datetime.fromisoformat(item["created_at"]) for item in self.store.backups()),
            default=None,
        )
        created = None
        if newest is None or now - newest >= timedelta(days=every_days):
            try:
                created = self.store.create_backup(automatic=True)
            except BackupBusy:
                return None
        automatic = sorted(
            (item for item in self.store.backups() if item.get("automatic")),
            key=lambda item: item["created_at"],
            reverse=True,
        )
        for old in automatic[keep:]:
            self.store.delete_backup(old["name"])
        return created

    def compact(self) -> dict:
        return self.store.compact()


class AutomaticBackup:
    """An independent scheduled check: no dependency on activity collection or sync."""

    def __init__(self, storage, every_days, keep):
        self.storage, self.every_days, self.keep = storage, every_days, keep

    def __call__(self, stop_event):
        if stop_event.is_set():
            return {"created": False, "stopped": True}
        backup = self.storage.backup_if_due(self.every_days, self.keep)
        return {"created": backup is not None, "backup_name": backup["name"] if backup else None}
