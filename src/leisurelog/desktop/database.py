"""Migrate the selected user's database before starting any background worker."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import URL

from leisurelog import DATABASE_REVISION
from leisurelog.desktop.paths import DesktopPaths, resources


def migration_config(database: Path):
    config = Config()
    config.set_main_option("script_location", str(resources() / "migrations").replace("%", "%%"))
    config.attributes["database_url"] = URL.create(
        "sqlite", database=str(database)
    ).render_as_string()
    return config


def database_revision(database: Path):
    if not database.exists() or database.stat().st_size == 0:
        return None
    with sqlite3.connect(database) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("数据库完整性检查失败；请保留文件并从备份恢复")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "alembic_version" not in tables:
            if tables:
                raise RuntimeError("数据库缺少版本信息，未执行自动修改")
            return None
        rows = db.execute("SELECT version_num FROM alembic_version").fetchall()
        if len(rows) != 1:
            raise RuntimeError("数据库版本信息不完整，未执行自动修改")
        return rows[0][0]


def copy_database(source: Path, destination: Path):
    with sqlite3.connect(source) as original, sqlite3.connect(destination) as target:
        original.backup(target)
        if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("数据库备份验证失败")


def prepare_database(paths: DesktopPaths):
    config = migration_config(paths.database)
    scripts = ScriptDirectory.from_config(config)
    if scripts.get_current_head() != DATABASE_REVISION:
        raise RuntimeError("程序与迁移文件不匹配，请重新安装完整版本")
    previous = database_revision(paths.database)
    if previous == DATABASE_REVISION:
        return {"from": previous, "to": previous, "backup": None}
    if previous:
        # An unknown/newer revision must never be downgraded or stamped silently.
        scripts.get_revision(previous)
    backup = None
    if previous:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = paths.root / "backups" / f"before-upgrade-{stamp}-{uuid4().hex[:6]}.db"
        copy_database(paths.database, backup)
    try:
        command.upgrade(config, "head")
        if database_revision(paths.database) != DATABASE_REVISION:
            raise RuntimeError("数据库升级未达到预期版本")
    except Exception as exc:
        if backup is not None:
            copy_database(backup, paths.database)
        raise RuntimeError("数据库升级失败，已有数据库已保留；请查看运行日志") from exc
    return {"from": previous, "to": DATABASE_REVISION, "backup": str(backup) if backup else None}
