"""Bounded, detached analysis inputs and declarative page resources."""

import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Protocol

from leisurelog.domain.plugins import PluginPermission, validate_plugin_id


def contribution_name(value):
    if type(value) is not str or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value):
        raise ValueError("贡献名称需要小写字母、数字或连字符")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("快照不能包含重复键")
        result[key] = value
    return result


def _json_value(value, depth=0):
    if depth > 32:
        raise ValueError("快照嵌套过深")
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("快照键需要字符串")
        for child in value.values():
            _json_value(child, depth + 1)
    elif type(value) is list:
        for child in value:
            _json_value(child, depth + 1)
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("快照不能包含无穷或非数字")
    elif value is not None and type(value) not in (str, int, bool):
        raise ValueError("快照只能包含 JSON 值")


@dataclass(frozen=True)
class JsonSnapshot:
    """A string owns no ORM objects; value() always returns a fresh copy."""

    json: str = "{}"

    def __post_init__(self):
        if type(self.json) is not str or len(self.json.encode("utf-8")) > 8 * 1024 * 1024:
            raise ValueError("快照最多 8 MiB")
        value = json.loads(self.json, object_pairs_hook=_unique)
        if type(value) is not dict:
            raise ValueError("快照根需要对象")
        _json_value(value)

    @classmethod
    def from_value(cls, value):
        _json_value(value)
        return cls(json.dumps(value, ensure_ascii=False, allow_nan=False))

    def value(self):
        return json.loads(self.json)


@dataclass(frozen=True)
class AnalysisRequest:
    parameters: JsonSnapshot
    data: JsonSnapshot = JsonSnapshot()

    def __post_init__(self):
        if type(self.parameters) is not JsonSnapshot or type(self.data) is not JsonSnapshot:
            raise TypeError("分析只接受 JSON 快照")
        if len(self.parameters.json.encode("utf-8")) > 16384:
            raise ValueError("分析参数最多 16 KiB")


@dataclass(frozen=True)
class GameTypeChange:
    """A proposal; primary=None requests removal of an existing manual choice."""

    key: str
    primary: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.key) is not str or not self.key or len(self.key) > 4096:
            raise ValueError("游戏条目标识无效")
        if self.primary is not None and (
            type(self.primary) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", self.primary)
        ):
            raise ValueError("游戏主类型标识无效")
        object.__setattr__(self, "tags", tuple(self.tags))
        if (
            len(self.tags) > 50
            or any(
                type(tag) is not str or not tag.strip() or len(tag.strip()) > 80
                for tag in self.tags
            )
            or (self.primary is None and self.tags)
        ):
            raise ValueError("游戏标签无效")


@dataclass(frozen=True)
class AnalysisResult:
    data: JsonSnapshot = JsonSnapshot()
    change: GameTypeChange | None = None

    def __post_init__(self):
        if type(self.data) is not JsonSnapshot:
            raise TypeError("分析结果需要 JSON 快照")
        if self.change is not None and type(self.change) is not GameTypeChange:
            raise TypeError("只能返回受控的人工类型建议")


class AnalysisRejected(ValueError):
    """An expected input error, distinct from a plugin execution failure."""

    def __init__(self, message: str, status: int = 422):
        if status not in (400, 404, 409, 422) or type(message) is not str or len(message) > 300:
            raise ValueError("无效的分析输入错误")
        self.message, self.status = message, status
        super().__init__(message)


class Analyzer(Protocol):
    def run(self, request: AnalysisRequest) -> AnalysisResult: ...


@dataclass(frozen=True)
class AnalyticsContribution:
    name: str
    analyzer: Analyzer
    permissions: tuple[PluginPermission, ...] = ()

    def __post_init__(self):
        contribution_name(self.name)
        if not callable(getattr(self.analyzer, "run", None)):
            raise ValueError("分析贡献需要 run(request)")
        object.__setattr__(self, "permissions", tuple(self.permissions))
        if any(type(value) is not PluginPermission for value in self.permissions):
            raise ValueError("分析权限无效")
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("分析权限不能重复")


def resource_name(value):
    if type(value) is not str or len(value) > 240 or "\\" in value:
        raise ValueError("页面资源必须使用受控相对路径")
    parts = value.split("/")
    if any(part in ("", ".", "..") or not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
        raise ValueError("页面资源不能逃逸根目录")
    if PurePosixPath(value).suffix not in {".html", ".js", ".css", ".svg", ".png", ".woff2"}:
        raise ValueError("页面资源格式不支持")


@dataclass(frozen=True)
class PageContribution:
    name: str
    title: str
    document: str
    assets: tuple[str, ...]

    def __post_init__(self):
        contribution_name(self.name)
        if type(self.title) is not str or not self.title.strip() or len(self.title) > 80:
            raise ValueError("页面标题无效")
        object.__setattr__(self, "assets", tuple(self.assets))
        if not 1 <= len(self.assets) <= 32 or len(set(self.assets)) != len(self.assets):
            raise ValueError("一个页面最多声明 32 个不重复资源")
        for value in self.assets:
            resource_name(value)
        if self.document not in self.assets or not self.document.endswith(".html"):
            raise ValueError("页面文档需要列入 HTML 资源清单")


@dataclass(frozen=True)
class ExtensionTicket:
    """Host-only activation provenance and shared request deadline."""

    owner: str
    generation: int
    deadline: float
    permissions: tuple[PluginPermission, ...] = ()


@dataclass(frozen=True)
class ExtensionEndpoint:
    """Reviewed host binding, deliberately absent from the public plugin SDK."""

    owner: str
    name: str
    method: str
    path: str
    query_type: type
    body_type: type | None = None


@dataclass(frozen=True)
class ExtensionPageRoute:
    owner: str
    name: str
    path: str


@dataclass(frozen=True)
class HostExtensionBindings:
    """Trusted assembly only; packages cannot choose handlers or resource roots."""

    endpoints: tuple[ExtensionEndpoint, ...] = ()
    pages: tuple[ExtensionPageRoute, ...] = ()
    resources: Mapping = field(default_factory=dict)
    hosts: Mapping[str, Callable] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("endpoints", "pages"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        for name in ("resources", "hosts"):
            values = dict(getattr(self, name) or {})
            for owner in values:
                validate_plugin_id(owner)
            object.__setattr__(self, name, MappingProxyType(values))
        if any(not callable(factory) for factory in self.hosts.values()):
            raise TypeError("宿主绑定需要显式的提供者工厂")
