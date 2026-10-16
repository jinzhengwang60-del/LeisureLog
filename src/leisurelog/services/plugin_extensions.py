"""Analysis/page lifecycle access; shared with the runtime's leases and workers."""

from dataclasses import dataclass
from time import monotonic

from leisurelog.domain.plugin_extensions import (
    AnalysisRejected,
    AnalysisRequest,
    AnalysisResult,
    ExtensionTicket,
    GameTypeChange,
    JsonSnapshot,
)
from leisurelog.domain.plugin_runtime import PluginExecutionError, PluginState
from leisurelog.domain.plugins import PluginCapability, PluginPermission


@dataclass(frozen=True)
class _Rejected:
    message: str
    status: int


class ExtensionExecutors:
    """The composition root selects host data providers; never a plugin factory."""

    def __init__(self, hosts):
        self._hosts = dict(hosts)

    def execute(self, endpoint, parameters):
        if endpoint.owner not in self._hosts:
            raise KeyError(endpoint.owner)
        return self._hosts[endpoint.owner].execute(endpoint, parameters)


class PluginExtensions:
    """Only the host sees tickets, transaction callbacks and resource declarations."""

    def __init__(self, lock, entries, workers, fault, problem, *, timeout=2):
        self._lock, self._entries, self._workers = lock, entries, workers
        self._fault, self._problem, self._timeout = fault, problem, timeout

    def _entry(self, owner, generation=None):
        entry = self._entries.get(owner)
        if (
            entry is None
            or entry.state != PluginState.RUNNING
            or (generation is not None and generation != entry.generation)
        ):
            self._problem("extension_inactive", owner, "功能插件已停用、失效或尚未启用")
        return entry

    def begin(self, owner, name, *, permissions=()):
        with self._lock:
            entry = self._entry(owner)
            self._analysis(entry, name)
            entry.lease.require(PluginCapability.ANALYTICS, *permissions)
            return ExtensionTicket(
                owner, entry.generation, monotonic() + self._timeout, tuple(permissions)
            )

    def _analysis(self, entry, name):
        contribution = next((c for c in entry.contributions.analytics if c.name == name), None)
        if contribution is None:
            self._problem("analysis_missing", entry.definition.manifest.plugin_id, "分析贡献不存在")
        entry.lease.require(PluginCapability.ANALYTICS, *contribution.permissions)
        return contribution

    def invoke(self, ticket, name, request):
        if type(request) is not AnalysisRequest:
            raise TypeError("宿主需要提供分析请求快照")
        with self._lock:
            entry = self._entry(ticket.owner, ticket.generation)
            contribution = self._analysis(entry, name)
            lease = entry.lease
            lease.require(PluginCapability.ANALYTICS, *ticket.permissions)

        def run():
            lease.require(
                PluginCapability.ANALYTICS, *contribution.permissions, *ticket.permissions
            )
            try:
                result = contribution.analyzer.run(request)
            except AnalysisRejected as error:
                checked = AnalysisRejected(error.message, error.status)
                return _Rejected(checked.message, checked.status)
            lease.require(
                PluginCapability.ANALYTICS, *contribution.permissions, *ticket.permissions
            )
            if type(result) is not AnalysisResult:
                raise TypeError("分析结果类型无效")
            change = result.change
            if change is not None:
                lease.require(PluginCapability.ANALYTICS, PluginPermission.GAME_TYPES_WRITE)
                change = GameTypeChange(change.key, change.primary, change.tags)
            return AnalysisResult(JsonSnapshot(result.data.json), change)

        remaining = ticket.deadline - monotonic()
        if remaining <= 0:
            self._problem("analysis_budget", ticket.owner, "本次分析超过请求预算")
        try:
            result = self._workers.call(
                ticket.owner, ticket.generation, run, remaining, channel="analysis"
            )
        except PluginExecutionError as error:
            if error.code not in {"call_busy", "worker_limit"}:
                self._fault(ticket.owner, ticket.generation, error.code)
            self._problem(error.code, ticket.owner, "分析暂时不可用，请检查插件状态")
        with self._lock:
            self._entry(ticket.owner, ticket.generation)
            lease.require(
                PluginCapability.ANALYTICS, *contribution.permissions, *ticket.permissions
            )
        if type(result) is _Rejected:
            raise AnalysisRejected(result.message, result.status)
        return result

    def commit(self, ticket, commit):
        with self._lock:
            entry = self._entry(ticket.owner, ticket.generation)
            entry.lease.require(
                PluginCapability.ANALYTICS, PluginPermission.GAME_TYPES_WRITE, *ticket.permissions
            )
            commit()

    def reject(self, ticket):
        self._fault(ticket.owner, ticket.generation, "invalid_analysis_result")
        self._problem("invalid_analysis_result", ticket.owner, "分析返回了不适用于本次操作的建议")

    def pages(self):
        with self._lock:
            return [
                (owner, entry.generation, page)
                for owner, entry in sorted(self._entries.items())
                if entry.state == PluginState.RUNNING
                and PluginCapability.PAGE in entry.definition.manifest.capabilities
                for page in entry.contributions.pages
            ]

    def page(self, owner, name=None, *, asset=None):
        with self._lock:
            entry = self._entry(owner)
            entry.lease.require(PluginCapability.PAGE)
            for page in entry.contributions.pages:
                if (name is not None and page.name == name) or (
                    asset is not None and asset in page.assets
                ):
                    return ExtensionTicket(owner, entry.generation, 0), page
            raise KeyError(name or asset)

    def check_page(self, ticket):
        with self._lock:
            self._entry(ticket.owner, ticket.generation).lease.require(PluginCapability.PAGE)
