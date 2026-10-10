from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEISURELOG_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/leisurelog.db"
    backup_dir: Path | None = None
    activitywatch_url: str = "http://127.0.0.1:5600"
    browser_device_bindings: dict[str, str] = Field(default_factory=dict)
    rules_path: Path = Path("config/rules.yaml")
    playnite_export_path: Path = Path("data/playnite-library.json")
    playnite_bindings_path: Path = Path("config/playnite-processes.yaml")
    session_gap_seconds: float = Field(default=60, ge=0, le=3600)
    auto_sync_enabled: bool = True
    auto_sync_interval_seconds: float = Field(default=60, ge=1, le=86400)
    auto_sync_overlap_seconds: int = Field(default=600, ge=60, le=86400)
    auto_sync_initial_hours: int = Field(default=24, ge=1, le=168)
    auto_backup_days: int = Field(default=7, ge=0, le=365)  # 0 turns automatic backups off
    auto_backup_keep: int = Field(default=4, ge=1, le=100)
