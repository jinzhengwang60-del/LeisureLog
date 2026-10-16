"""Atomic local plugin intent; no executable package paths or raw activity data."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from leisurelog.domain.plugin_runtime import PluginConfiguration
from leisurelog.domain.plugins import PluginPermission

_MAX_BYTES = 1024 * 1024


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("插件配置包含重复键")
        result[key] = value
    return result


class PluginConfigurationConflict(ValueError):
    pass


class FilePluginState:
    """One host per data directory. Revision checks detect stale/external edits."""

    def __init__(self, path: Path, *, defaults: PluginConfiguration | None = None):
        self.path = path
        self.defaults = defaults or PluginConfiguration()

    def load(self) -> PluginConfiguration:
        try:
            raw = self._read_bytes()
        except FileNotFoundError:
            return self.defaults
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        if (
            type(value) is not dict
            or set(value) != {"version", "revision", "enabled"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or type(value["enabled"]) is not dict
            or any(type(grants) is not list for grants in value["enabled"].values())
        ):
            raise ValueError("插件配置格式不兼容")
        return PluginConfiguration(
            value["revision"],
            {
                key: tuple(PluginPermission(grant) for grant in grants)
                for key, grants in value["enabled"].items()
            },
        )

    def _read_bytes(self):
        with self.path.open("rb") as source:
            value = source.read(_MAX_BYTES + 1)
        if len(value) > _MAX_BYTES:
            raise ValueError("插件选择文件超过大小限制")
        return value

    @staticmethod
    def _payload(config):
        return {
            "version": 1,
            "revision": config.revision,
            "enabled": {
                key: [grant.value for grant in grants]
                for key, grants in sorted(config.enabled.items())
            },
        }

    def backup_snapshot(self) -> bytes:
        # Atomic replacement means one open descriptor sees one complete choice.
        # Preserve damaged files for recovery rather than silently resetting them.
        try:
            value = self._read_bytes()
        except FileNotFoundError:
            # Capture today's explicit defaults, without creating a live file.
            value = json.dumps(
                self._payload(self.defaults),
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
        if len(value) > _MAX_BYTES:
            raise ValueError("插件选择文件超过备份大小限制")
        return value

    def save(self, config: PluginConfiguration, *, expected_revision: int) -> None:
        if self.load().revision != expected_revision:
            raise PluginConfigurationConflict("插件配置已被其他操作修改，请重启后核对")
        if config.revision != expected_revision + 1:
            raise ValueError("插件配置代数必须递增")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=self.path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary = Path(output.name)
                json.dump(
                    self._payload(config),
                    output,
                    ensure_ascii=False,
                    indent=2,
                )
                output.flush()
                os.fsync(output.fileno())
            if temporary.stat().st_size > _MAX_BYTES:
                raise ValueError("插件选择文件超过大小限制")
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
