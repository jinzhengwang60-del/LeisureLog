"""Bundled resources and writable user files have separate roots."""

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


def resources() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[3]


def default_data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local:
        return Path(local) / "LeisureLog"
    return Path.home() / ".local" / "share" / "LeisureLog"


@dataclass(frozen=True)
class DesktopPaths:
    root: Path

    @property
    def database(self):
        return self.root / "data" / "leisurelog.db"

    @property
    def config(self):
        return self.root / "config"

    @property
    def preferences(self):
        return self.config / "desktop.json"

    @property
    def runtime(self):
        return self.root / "runtime.json"

    def prepare(self):
        for folder in ("data", "config", "backups", "logs"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        for source, name in (
            (resources() / "config" / "rules.yaml", "rules.yaml"),
            (resources() / "packaging/defaults/playnite-processes.yaml", "playnite-processes.yaml"),
        ):
            target = self.config / name
            if not target.exists():
                shutil.copyfile(source, target)
