"""Plugin metadata and activation plans; no imports, persistence or execution."""

import re
from dataclasses import dataclass
from enum import Enum

PLUGIN_API_VERSION = 1
_PLUGIN_ID = re.compile(r"[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+\Z")


def validate_plugin_id(value: str) -> None:
    if not isinstance(value, str) or len(value) > 100 or not _PLUGIN_ID.fullmatch(value):
        raise ValueError("插件 ID 必须使用小写的命名空间，例如 leisurelog.game-library")
    if value.startswith("core."):
        raise ValueError("core 命名空间由基础程序保留")


class PluginCapability(str, Enum):
    GAME_CATALOG = "game-catalog"
    SOURCE = "source"
    CLASSIFIER = "classifier"
    ANALYTICS = "analytics"
    PAGE = "page"
    THEME = "theme"
    TASK = "task"


class PluginPermission(str, Enum):
    GAME_STATISTICS_READ = "games.statistics.read"
    GAME_TYPES_WRITE = "games.types.write"
    GAME_CATALOG_READ = "games.catalog.read"
    GAME_CATALOG_PROPOSE = "games.catalog.propose"
    SUMMARY_READ = "activity.summary.read"
    DETAILS_READ = "activity.details.read"
    CLASSIFICATION_PROPOSE = "classification.propose"
    FILE_IMPORT = "files.import"
    FILE_EXPORT = "files.export"
    NETWORK = "network.request"


@dataclass(frozen=True)
class PluginDependency:
    plugin_id: str
    version_spec: str

    def __post_init__(self):
        validate_plugin_id(self.plugin_id)
        if not isinstance(self.version_spec, str) or not self.version_spec.strip():
            raise ValueError("插件依赖必须声明兼容版本")


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    requires_app: str
    api_version: int
    capabilities: tuple[PluginCapability, ...] = ()
    permissions: tuple[PluginPermission, ...] = ()
    dependencies: tuple[PluginDependency, ...] = ()

    def __post_init__(self):
        validate_plugin_id(self.plugin_id)
        for value in (self.name, self.version, self.requires_app):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("插件名称、版本与应用版本范围不能为空")
        if type(self.api_version) is not int or self.api_version < 1:
            raise ValueError("插件接口版本必须是正整数")
        for field in ("capabilities", "permissions", "dependencies"):
            object.__setattr__(self, field, tuple(getattr(self, field)))
        if any(not isinstance(v, PluginCapability) for v in self.capabilities):
            raise ValueError("未知插件能力")
        if any(not isinstance(v, PluginPermission) for v in self.permissions):
            raise ValueError("未知插件权限声明")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("插件能力声明不能重复")
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("插件权限声明不能重复")
        ids = [d.plugin_id for d in self.dependencies]
        if self.plugin_id in ids or len(set(ids)) != len(ids):
            raise ValueError("插件不能依赖自身或重复声明同一个依赖")


@dataclass(frozen=True)
class PluginIssue:
    code: str
    plugin_id: str
    message: str


class PluginResolutionError(ValueError):
    def __init__(self, issue: PluginIssue):
        self.issue = issue
        super().__init__(issue.message)


@dataclass(frozen=True)
class PluginActivationPlan:
    requested: tuple[str, ...]
    ordered: tuple[str, ...]
    implicit_dependencies: tuple[str, ...]
