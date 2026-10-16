"""Small host contracts. Task execution and resource loading are not implemented here."""

import math
import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Protocol


def _seconds(value: float, *, positive: bool = False) -> None:
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("时长必须是有限数值")
    if value < 0 or (positive and value == 0):
        raise ValueError("时长必须为正数" if positive else "时长不能为负数")


@dataclass(frozen=True)
class SummaryQuery:
    """Inclusive calendar dates in the host's timezone, without a history retention limit."""

    start: date
    end: date
    purpose: str | None = None
    project_id: str | None = None

    def __post_init__(self):
        if type(self.start) is not date or type(self.end) is not date or self.end < self.start:
            raise ValueError("汇总需要有效的起止日期")
        for value in (self.purpose, self.project_id):
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError("筛选条件应为非空字符串或 None")


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    active_seconds: float

    def __post_init__(self):
        if type(self.category) is not str or not self.category.strip():
            raise ValueError("汇总类别不能为空")
        _seconds(self.active_seconds)


@dataclass(frozen=True)
class ActivitySummary:
    """A detached projection: no event IDs, titles, URLs or raw payloads."""

    total_active_seconds: float
    by_category: tuple[CategoryTotal, ...] = ()

    def __post_init__(self):
        _seconds(self.total_active_seconds)
        object.__setattr__(self, "by_category", tuple(self.by_category))
        if any(type(value) is not CategoryTotal for value in self.by_category):
            raise ValueError("汇总只能包含类别与有效时长")
        categories = [value.category for value in self.by_category]
        if len(set(categories)) != len(categories):
            raise ValueError("汇总类别不能重复")
        total = sum(value.active_seconds for value in self.by_category)
        if not math.isclose(total, self.total_active_seconds, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("类别有效时长之和必须等于汇总有效时长")


class SummaryReader(Protocol):
    def read(self, query: SummaryQuery) -> ActivitySummary: ...


@dataclass(frozen=True)
class ThemeContribution:
    """A local CSS resource descriptor; the host assigns its plugin namespace."""

    key: str
    name: str
    css_path: str

    def __post_init__(self):
        if type(self.key) is not str or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", self.key):
            raise ValueError("风格标识应使用小写字母、数字或连字符")
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("风格名称不能为空")
        path = self.css_path
        if (
            type(path) is not str
            or not path.endswith(".css")
            or any(char in path for char in ("\\", ":", "\x00", "?", "#"))
            or any(part in ("", ".", "..") for part in path.split("/"))
        ):
            raise ValueError("CSS 必须使用插件包内的相对路径")


@dataclass(frozen=True)
class TaskBudget:
    """Requested host budgets, not an executor or a promise to kill Python threads."""

    run_timeout_seconds: float = 30
    stop_timeout_seconds: float = 5

    def __post_init__(self):
        _seconds(self.run_timeout_seconds, positive=True)
        _seconds(self.stop_timeout_seconds, positive=True)


class TaskStopResult(str, Enum):
    STOPPED = "stopped"
    TIMED_OUT = "timed_out"


class TaskContext(Protocol):
    """Created by the host for one owner. Tasks cooperate with the stop signal."""

    @property
    def owner_plugin_id(self) -> str: ...

    def stop_requested(self) -> bool: ...

    def wait_for_stop(self, timeout_seconds: float) -> bool: ...


class PluginTask(Protocol):
    def run(self, context: TaskContext) -> None: ...


class TaskHandle(Protocol):
    @property
    def owner_plugin_id(self) -> str: ...

    def request_stop(self) -> None: ...

    def wait_stopped(self, timeout_seconds: float) -> TaskStopResult: ...
