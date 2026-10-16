import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import delete, select

from leisurelog.domain.game_catalog import GameCatalogSnapshot
from leisurelog.domain.games import Game
from leisurelog.repositories.models import GameCatalogRow, GameSnapshotRow


class SQLiteGameCatalog:
    def __init__(self, db):
        self.db = db

    def games(self):
        return [
            Game(row.id, row.name, row.installed, row.directory, tuple(row.tags),
                 tuple(tuple(m) for m in row.matches))
            for row in self.db.scalars(select(GameCatalogRow).order_by(GameCatalogRow.name))
        ]

    def snapshot(self):
        latest = self.db.scalar(select(GameSnapshotRow).order_by(GameSnapshotRow.id.desc()))
        return GameCatalogSnapshot(
            latest.digest if latest else "empty", tuple(self.games()), namespace="playnite"
        )

    def replace(self, payload, games):
        normalized = {
            "source": {k: v for k, v in payload.items() if k != "exported_at"},
            "games": [asdict(game) for game in games],
        }
        digest = hashlib.sha256(
            json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        latest = self.db.scalar(select(GameSnapshotRow).order_by(GameSnapshotRow.id.desc()))
        if latest is not None and latest.digest == digest:
            return False
        snapshot = GameSnapshotRow(
            digest=digest, payload=payload, imported_at=datetime.now(timezone.utc)
        )
        self.db.add(snapshot)
        self.db.flush()
        self.db.execute(delete(GameCatalogRow))
        self.db.add_all([
            GameCatalogRow(id=g.id, name=g.name, installed=g.installed, directory=g.directory,
                           tags=list(g.tags), matches=[list(m) for m in g.matches],
                           snapshot_id=snapshot.id)
            for g in games
        ])
        self.db.flush()
        return True

    def status(self):
        latest = self.db.scalar(select(GameSnapshotRow).order_by(GameSnapshotRow.id.desc()))
        games = self.games()
        return {
            "connected": latest is not None,
            "imported_at": latest.imported_at if latest else None,
            "total": len(games), "installed": sum(g.installed for g in games),
            "recognizable": sum(g.installed and bool(g.matches) for g in games),
            "games": [asdict(game) for game in games],
        }
