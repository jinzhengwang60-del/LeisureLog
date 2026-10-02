"""SQLite online snapshots and isolated restore verification."""

import hashlib
import json
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from leisurelog.domain.storage import BackupBusy

SUPERSEDED = """
SELECT r.id FROM raw_events r
WHERE NOT EXISTS (SELECT 1 FROM activity_events a WHERE a.raw_event_id=r.id)
AND NOT EXISTS (SELECT 1 FROM idle_events i WHERE i.raw_event_id=r.id)
AND NOT EXISTS (SELECT 1 FROM browser_events b WHERE b.raw_event_id=r.id)
AND (EXISTS (SELECT 1 FROM activity_events a WHERE a.id=r.event_id)
     OR EXISTS (SELECT 1 FROM idle_events i WHERE i.id=r.event_id)
     OR EXISTS (SELECT 1 FROM browser_events b WHERE b.id=r.event_id))
"""

BACKUP_NAME = re.compile(r"leisurelog-\d{8}T\d{6}Z-[a-f0-9]{12}\.db\Z")


def connect_readonly(path: Path):
    return closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30))


def fingerprint(db) -> dict:
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    result = {}
    for (table,) in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        # Hash sorted row digests: stable despite row order, with duplicates preserved.
        rows = sorted(
            hashlib.sha256(json.dumps(row, ensure_ascii=False).encode()).hexdigest()
            for row in db.execute(f"SELECT * FROM {quoted}")
        )
        result[table] = {
            "count": len(rows),
            "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest(),
        }
    return result


def verify_restore(snapshot: Path) -> dict:
    # Never replace the live database. Restore the snapshot into a disposable database.
    with TemporaryDirectory(prefix="leisurelog-restore-") as directory:
        restored = Path(directory) / "restored.db"
        with connect_readonly(snapshot) as source:
            with closing(sqlite3.connect(restored)) as target:
                source.backup(target)
            expected = fingerprint(source)
            schema = source.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
        with connect_readonly(restored) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Backup integrity verification failed")
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Backup foreign key verification failed")
            actual_schema = db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
            if fingerprint(db) != expected or actual_schema != schema:
                raise ValueError("Restored data differs from backup")
            revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        return {"verified": True, "database_revision": revision, "tables": expected}


class SQLiteStorage:
    def __init__(self, database: Path, rules_path: Path, backup_dir: Path | None = None):
        self.database = database.resolve()
        self.rules_path = rules_path.resolve()
        self.directory = (backup_dir or self.database.parent / "backups").resolve()
        self.lock = Lock()

    def info(self) -> dict:
        with connect_readonly(self.database) as db:
            db.execute("BEGIN")
            counts = {
                table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in (
                    "activity_events",
                    "sessions",
                    "raw_events",
                    "idle_events",
                    "manual_overrides",
                    "learned_rules",
                    "browser_events",
                    "segment_overrides",
                    "timing_overrides",
                    "content_items",
                    "content_aliases",
                    "game_catalog",
                    "game_snapshots",
                    "game_type_overrides",
                )
            }
            removable = db.execute("SELECT count(*) FROM (" + SUPERSEDED + ")").fetchone()[0]
            earliest, latest = db.execute(
                "SELECT min(start_time), max(end_time) FROM "
                "(SELECT start_time,end_time FROM activity_events "
                "UNION ALL SELECT start_time,end_time FROM idle_events)"
            ).fetchone()
        sizes = {
            "database_bytes": self.database.stat().st_size,
            "wal_bytes": self._size(Path(str(self.database) + "-wal")),
            "shm_bytes": self._size(Path(str(self.database) + "-shm")),
        }
        backup_bytes = (
            sum(file.stat().st_size for file in self.directory.iterdir() if file.is_file())
            if self.directory.exists()
            else 0
        )
        return {
            "database_path": str(self.database),
            "backup_directory": str(self.directory),
            **sizes,
            "live_bytes": sum(sizes.values()),
            "backup_bytes": backup_bytes,
            "counts": counts,
            "superseded_snapshots": removable,
            "earliest_record_at": earliest.replace(" ", "T") + "+00:00" if earliest else None,
            "latest_record_at": latest.replace(" ", "T") + "+00:00" if latest else None,
        }

    @staticmethod
    def _size(path: Path) -> int:
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return 0

    def backups(self) -> list[dict]:
        if not self.directory.exists():
            return []
        result = []
        for path in sorted(self.directory.glob("leisurelog-*.db"), reverse=True):
            if not BACKUP_NAME.fullmatch(path.name):
                continue
            try:
                manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            result.append(
                {
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "created_at": manifest["created_at"],
                    "verified": manifest["verification"]["verified"],
                    "counts": {
                        k: v["count"] for k, v in manifest["verification"]["tables"].items()
                    },
                    "download_url": f"/api/storage/backups/{path.name}/download",
                    "archive_url": f"/api/storage/backups/{path.name}/archive",
                }
            )
        return result

    def download_path(self, name: str) -> Path:
        if not BACKUP_NAME.fullmatch(name):
            raise KeyError(name)
        path = self.directory / name
        if not path.is_file() or path.is_symlink() or not path.with_suffix(".json").is_file():
            raise KeyError(name)
        return path

    def create_backup(self) -> dict:
        if not self.lock.acquire(blocking=False):
            raise BackupBusy()
        try:
            return self._create_backup()
        finally:
            self.lock.release()

    def _create_backup(self) -> dict:
        self.directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        name = f"leisurelog-{now:%Y%m%dT%H%M%SZ}-{uuid4().hex[:12]}.db"
        path = self.directory / name
        temporary = path.with_suffix(".partial")
        try:
            with connect_readonly(self.database) as source:
                with closing(sqlite3.connect(temporary)) as target:
                    source.backup(target, pages=256, sleep=0.01)
                    target.execute("PRAGMA journal_mode=DELETE")
            verification = verify_restore(temporary)
            # Keep the YAML classifier config beside the DB. User rules are already in DB.
            shutil.copyfile(self.rules_path, path.with_suffix(".rules.yaml"))
            manifest = {"created_at": now.isoformat(), "verification": verification}
            path.with_suffix(".json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            archive = path.with_suffix(".zip.partial")
            with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
                bundle.write(temporary, "leisurelog.db")
                bundle.write(path.with_suffix(".rules.yaml"), "config/rules.yaml")
                bundle.write(path.with_suffix(".json"), "verification.json")
            archive.replace(path.with_suffix(".zip"))
            temporary.replace(path)
        except Exception:
            for item in (
                temporary,
                path.with_suffix(".zip.partial"),
                path.with_suffix(".zip"),
                path.with_suffix(".json"),
                path.with_suffix(".rules.yaml"),
            ):
                item.unlink(missing_ok=True)
            raise
        return next(item for item in self.backups() if item["name"] == name)

    def compact(self) -> dict:
        if not self.lock.acquire(blocking=False):
            raise BackupBusy()
        try:
            before = self.info()
            if before["superseded_snapshots"] == 0:
                return {
                    "deleted_snapshots": 0,
                    "backup": None,
                    "before_bytes": before["live_bytes"],
                    "after_bytes": before["live_bytes"],
                    "vacuum_completed": False,
                    "message": "No superseded snapshots",
                }
            backup = self._create_backup()
            # Only delete candidates present in the verified backup, never later unbacked revisions.
            with connect_readonly(self.download_path(backup["name"])) as snapshot:
                candidates = snapshot.execute(SUPERSEDED).fetchall()
            with closing(sqlite3.connect(self.database, timeout=30)) as db:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("BEGIN IMMEDIATE")
                try:
                    db.execute("CREATE TEMP TABLE compact_candidates (id INTEGER PRIMARY KEY)")
                    db.executemany("INSERT INTO compact_candidates VALUES (?)", candidates)
                    cursor = db.execute(
                        "DELETE FROM raw_events WHERE id IN (" + SUPERSEDED + ") "
                        "AND id IN (SELECT id FROM compact_candidates)"
                    )
                    removed = cursor.rowcount
                    if db.execute("PRAGMA foreign_key_check").fetchall():
                        raise ValueError("Compaction foreign key verification failed")
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
                warning = None
                try:
                    db.execute("VACUUM")
                    checkpoint = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    if checkpoint[0]:
                        warning = "WAL still in use; log space will be reclaimed later"
                    vacuum_completed = True
                except sqlite3.Error:
                    vacuum_completed = False
                    warning = "Snapshots compacted; file space reclamation deferred"
            after = self.info()
            result = {
                "deleted_snapshots": removed,
                "backup": backup,
                "before_bytes": before["live_bytes"],
                "after_bytes": after["live_bytes"],
                "vacuum_completed": vacuum_completed,
                "warning": warning,
            }
            return result
        finally:
            self.lock.release()
