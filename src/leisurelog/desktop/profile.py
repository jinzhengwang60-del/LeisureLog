"""Explicit desktop configuration does not read the developer's .env or working directory."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.engine import URL

from leisurelog.config import Settings
from leisurelog.desktop.paths import DesktopPaths


def write_json(path: Path, value):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(path)


def local_activitywatch_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not parsed.port
    ):
        raise ValueError("ActivityWatch 地址必须是本机 HTTP 地址，并包含端口")
    return value.rstrip("/")


class DesktopPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    setup_completed: bool = False
    sync_enabled: bool = False
    activitywatch_url: str = "http://127.0.0.1:5600"
    initial_hours: int = 1
    web_port: int = Field(default=8001, ge=1, le=65535)

    @field_validator("activitywatch_url")
    @classmethod
    def validate_url(cls, value):
        return local_activitywatch_url(value)

    @field_validator("initial_hours")
    @classmethod
    def validate_hours(cls, value):
        if value not in {1, 24}:
            raise ValueError("首次导入范围只能是最近 1 小时或 24 小时")
        return value

    @classmethod
    def load(cls, paths: DesktopPaths):
        if paths.preferences.exists():
            return cls.model_validate_json(paths.preferences.read_text(encoding="utf-8"))
        return cls()

    def save(self, paths: DesktopPaths):
        write_json(paths.preferences, self.model_dump())

    def settings(self, paths: DesktopPaths):
        return DesktopSettings(
            _env_file=None,
            database_url=URL.create("sqlite", database=str(paths.database)).render_as_string(),
            backup_dir=paths.root / "backups",
            activitywatch_url=self.activitywatch_url,
            browser_device_bindings={},
            rules_path=paths.config / "rules.yaml",
            playnite_export_path=paths.root / "data/playnite-library.json",
            playnite_bindings_path=paths.config / "playnite-processes.yaml",
            session_gap_seconds=60,
            auto_sync_enabled=self.setup_completed and self.sync_enabled,
            auto_sync_interval_seconds=60,
            auto_sync_overlap_seconds=600,
            auto_sync_initial_hours=self.initial_hours,
            auto_backup_days=7,
            auto_backup_keep=4,
            auto_backup_check_seconds=3600,
        )


class DesktopSettings(Settings):
    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        # Even a malformed inherited environment variable must not select another user's data.
        return (init_settings,)
