"""Host lifecycle contracts, detached state and declarative contributions."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Protocol

from leisurelog.domain.game_catalog import (
    GameCatalogClassifier,
    GameCatalogFilesReader,
    GameCatalogImport,
    GameCatalogSource,
)
from leisurelog.domain.plugin_contracts import (
    PluginTask,
    SummaryReader,
    TaskBudget,
    TaskStopResult,
    _seconds,
)
from leisurelog.domain.plugin_extensions import AnalyticsContribution, PageContribution
from leisurelog.domain.plugins import PluginManifest, PluginPermission, validate_plugin_id
from leisurelog.domain.ports import Classifier


class PluginState(str, Enum):
    DISABLED = "disabled"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ScheduledTask:
    name: str
    task: PluginTask
    interval_seconds: float = 60
    budget: TaskBudget = field(default_factory=TaskBudget)

    def __post_init__(self):
        if type(self.name) is not str or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", self.name):
            raise ValueError("任务名称需要小写字母、数字或连字符")
        if not callable(getattr(self.task, "run", None)) or type(self.budget) is not TaskBudget:
            raise ValueError("任务需要 run(context) 和 TaskBudget")
        _seconds(self.interval_seconds, positive=True)
        if self.interval_seconds > 86400:
            raise ValueError("任务间隔不能超过一天")


@dataclass(frozen=True)
class PluginContributions:
    classifiers: tuple[Classifier, ...] = ()
    tasks: tuple[ScheduledTask, ...] = ()
    game_catalog: GameCatalogSource | None = None
    game_classifier: GameCatalogClassifier | None = None
    analytics: tuple[AnalyticsContribution, ...] = ()
    pages: tuple[PageContribution, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "classifiers", tuple(self.classifiers))
        object.__setattr__(self, "tasks", tuple(self.tasks))
        for name, expected in (("analytics", AnalyticsContribution), ("pages", PageContribution)):
            values = tuple(getattr(self, name))
            if len(values) > 16 or any(type(value) is not expected for value in values):
                raise ValueError("一个插件最多提供 16 个有效分析贡献和 16 个页面")
            if len({value.name for value in values}) != len(values):
                raise ValueError("同一插件的贡献名称不能重复")
            object.__setattr__(self, name, values)
        if len(self.classifiers) + int(self.game_classifier is not None) > 4 or len(self.tasks) > 8:
            raise ValueError("一个插件最多注册 4 个分类器和 8 个任务")
        if any(not callable(getattr(value, "classify", None)) for value in self.classifiers):
            raise ValueError("分类贡献需要 classify(event)")
        if any(type(value) is not ScheduledTask for value in self.tasks):
            raise ValueError("任务贡献需要 ScheduledTask")
        if len({value.name for value in self.tasks}) != len(self.tasks):
            raise ValueError("同一插件的任务名称不能重复")
        if self.game_catalog is not None and not callable(
            getattr(self.game_catalog, "fetch", None)
        ):
            raise ValueError("游戏资料贡献需要 fetch()")
        if self.game_classifier is not None and not callable(
            getattr(self.game_classifier, "classify", None)
        ):
            raise ValueError("游戏匹配贡献需要 classify(event, catalog)")


@dataclass(frozen=True)
class PluginContext:
    plugin_id: str
    summary: SummaryReader | None = None
    game_files: GameCatalogFilesReader | None = None


@dataclass(frozen=True)
class GameCatalogTicket:
    """Host-only activation provenance; never exported to plugin code."""

    owner: str
    generation: int
    proposal: GameCatalogImport


@dataclass(frozen=True)
class PluginDefinition:
    manifest: PluginManifest
    create: Callable[[PluginContext], PluginContributions]
    priority: int = 100
    required_permissions: tuple[PluginPermission, ...] = ()

    def __post_init__(self):
        if not callable(self.create) or type(self.priority) is not int:
            raise ValueError("插件需要创建函数与整数优先级")
        object.__setattr__(self, "required_permissions", tuple(self.required_permissions))
        if any(type(value) is not PluginPermission for value in self.required_permissions) or (
            len(set(self.required_permissions)) != len(self.required_permissions)
            or not set(self.required_permissions) <= set(self.manifest.permissions)
        ):
            raise ValueError("宿主必需权限必须属于插件声明且不能重复")


@dataclass(frozen=True)
class PluginConfiguration:
    revision: int = 0
    enabled: Mapping[str, tuple[PluginPermission, ...]] = field(default_factory=dict)

    def __post_init__(self):
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("配置代数必须是非负整数")
        values = {}
        for plugin_id, permissions in self.enabled.items():
            validate_plugin_id(plugin_id)
            permissions = tuple(permissions)
            if any(type(value) is not PluginPermission for value in permissions):
                raise ValueError("配置包含未知权限")
            if len(set(permissions)) != len(permissions):
                raise ValueError("配置权限不能重复")
            values[plugin_id] = permissions
        object.__setattr__(self, "enabled", MappingProxyType(values))


class PluginStateStore(Protocol):
    def load(self) -> PluginConfiguration: ...

    def save(self, config: PluginConfiguration, *, expected_revision: int) -> None: ...


class PluginExecutionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class PluginWorkers(Protocol):
    def set_failure_handler(self, handler: Callable[[str, int, str], None]) -> None: ...

    def call(
        self,
        owner: str,
        generation: int,
        run: Callable,
        timeout: float,
        *,
        channel: str = "call",
    ): ...

    def start(self, owner: str, generation: int, task: ScheduledTask) -> None: ...

    def check_capacity(self, additional: int) -> None: ...

    def request_stop(self, owner: str) -> None: ...

    def wait_stopped(self, owner: str, timeout: float) -> TaskStopResult: ...

    def busy(self, owner: str) -> bool: ...

    def forget(self, owner: str) -> None: ...

    def snapshot(self, owner: str) -> list[dict]: ...

    def close(self, timeout: float) -> bool: ...

    def when_drained(self, callback: Callable[[], None]) -> None: ...
