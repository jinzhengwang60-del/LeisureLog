"""Serial lifecycle changes and revocable contributions; execution is injected."""

from dataclasses import dataclass, field
from threading import RLock
from time import monotonic

from leisurelog.domain.game_catalog import GameCatalogSnapshot, GameCatalogUnavailable
from leisurelog.domain.models import ActivityEvent
from leisurelog.domain.plugin_contracts import SummaryReader, TaskStopResult, _seconds
from leisurelog.domain.plugin_extensions import AnalyticsContribution, PageContribution
from leisurelog.domain.plugin_runtime import (
    GameCatalogTicket,
    PluginConfiguration,
    PluginContext,
    PluginContributions,
    PluginDefinition,
    PluginExecutionError,
    PluginState,
    PluginStateStore,
    PluginWorkers,
)
from leisurelog.domain.plugins import (
    PluginCapability,
    PluginIssue,
    PluginPermission,
    PluginResolutionError,
)
from leisurelog.services.plugin_access import (
    PluginAccessLease,
    PluginClassifier,
    PluginGameCatalog,
    PluginGameClassifier,
    PluginGameFiles,
    PluginSummaryReader,
)
from leisurelog.services.plugin_extensions import PluginExtensions
from leisurelog.services.plugin_management import enable_targets, stop_targets
from leisurelog.services.plugin_policy import (
    SUPPORTED_CAPABILITIES as _SUPPORTED,
)
from leisurelog.services.plugin_policy import (
    SUPPORTED_PERMISSIONS as _PERMISSIONS,
)
from leisurelog.services.plugin_policy import required_permissions
from leisurelog.services.plugin_registry import PluginRegistry

_MESSAGES = {
    "call_exception": "插件调用出错，相关能力已撤下",
    "call_timeout": "插件调用超时，相关能力已撤下",
    "task_exception": "插件任务出错，相关能力已撤下",
    "task_timeout": "插件任务超过运行预算，已发出停止信号",
    "stop_timeout": "插件尚未确认停止，禁止重复启动",
    "dependency_failed": "所依赖的插件不可用，相关能力已撤下",
    "configuration_invalid": "插件配置无法读取；核心继续运行，请修复配置后重启",
    "catalog_read_failed": "已保存游戏资料无法读取，游戏匹配已撤下；核心继续运行",
}


class _CatalogMiss:
    pass


class _ClassifierBatch:
    def __init__(self, runtime, selected, catalog):
        self._runtime, self._selected, self._catalog = runtime, selected, catalog
        self._identities = {game.id: game for game in catalog.games}
        self._apps = {
            app.casefold() for game in catalog.games if game.installed for app, _ in game.matches
        }

    def classify(self, event):
        return self._runtime._classify(
            event, self._selected, self._catalog, self._identities, self._apps
        )


class PluginOperationError(RuntimeError):
    def __init__(self, issue: PluginIssue):
        self.issue = issue
        super().__init__(issue.message)


def _problem(code, plugin_id, message):
    raise PluginOperationError(PluginIssue(code, plugin_id, message))


def _create_contributions(definition, context, page_validator):
    result = definition.create(context)
    if type(result) is not PluginContributions:
        return result
    # Revalidate detached descriptors inside the owned factory call, including
    # instances changed with object.__setattr__; nothing runs on the control thread.
    checked = PluginContributions(
        result.classifiers,
        result.tasks,
        result.game_catalog,
        result.game_classifier,
        tuple(AnalyticsContribution(c.name, c.analyzer, c.permissions) for c in result.analytics),
        tuple(PageContribution(p.name, p.title, p.document, p.assets) for p in result.pages),
    )
    if checked.pages and page_validator is not None:
        page_validator(definition.manifest.plugin_id, checked.pages)
    return checked


@dataclass
class _Entry:
    definition: PluginDefinition
    state: PluginState = PluginState.DISABLED
    generation: int = 0
    lease: PluginAccessLease | None = None
    contributions: PluginContributions = field(default_factory=PluginContributions)
    classifiers: tuple = ()
    game_catalog: PluginGameCatalog | None = None
    game_classifier: PluginGameClassifier | None = None
    catalog_issue: PluginIssue | None = None
    issue: PluginIssue | None = None


class PluginRuntime:
    def __init__(
        self,
        definitions: tuple[PluginDefinition, ...],
        workers: PluginWorkers,
        store: PluginStateStore,
        summary: SummaryReader,
        *,
        app_version: str,
        call_timeout: float = 0.25,
        startup_timeout: float = 2,
        stop_timeout: float = 2,
        catalog_reader=None,
        catalog_files=None,
        catalog_timeout: float = 2,
        analysis_timeout: float = 2,
        page_validator=None,
    ):
        if len(definitions) > 64:
            raise ValueError("一个宿主最多登记 64 个插件")
        budgets = (call_timeout, startup_timeout, stop_timeout, catalog_timeout, analysis_timeout)
        for value in budgets:
            _seconds(value, positive=True)
            if value > 300:
                raise ValueError("宿主调用或停止预算不能超过五分钟")
        self._registry = PluginRegistry([value.manifest for value in definitions])
        self._entries = {value.manifest.plugin_id: _Entry(value) for value in definitions}
        self._workers, self._store, self._summary = workers, store, summary
        self._catalog_reader, self._catalog_files = catalog_reader, dict(catalog_files or {})
        self._catalog_timeout = catalog_timeout
        self._page_validator = page_validator
        self._app_version = app_version
        self._call_timeout, self._startup_timeout, self._stop_timeout = (
            call_timeout,
            startup_timeout,
            stop_timeout,
        )
        self._control, self._state_lock = RLock(), RLock()
        self.extensions = PluginExtensions(
            self._state_lock,
            self._entries,
            workers,
            self._fault,
            _problem,
            timeout=analysis_timeout,
        )
        self._started, self._closing, self._generation = False, False, 0
        self._restore_attempted = set()
        self._restore_deadline = None
        self._orphans = {}
        self._config_error = None
        try:
            self._config = store.load()
        except Exception:
            self._config = PluginConfiguration()
            self._config_error = PluginIssue(
                "configuration_invalid",
                "",
                _MESSAGES["configuration_invalid"],
            )
        workers.set_failure_handler(self._fault)

    def _check_mutation(self, expected_revision):
        if self._closing:
            _problem("host_closed", "", "插件宿主正在关闭")
        if self._config_error:
            raise PluginOperationError(self._config_error)
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision != self._config.revision
        ):
            _problem("configuration_conflict", "", "插件设置已改变，请刷新后重试")

    def _save(self, enabled):
        updated = PluginConfiguration(self._config.revision + 1, enabled)
        try:
            self._store.save(updated, expected_revision=self._config.revision)
        except Exception:
            _problem("configuration_write_failed", "", "插件设置未能保存，当前设置未改变")
        self._config = updated

    def start(self):
        with self._control:
            if self._started or self._closing:
                return
            self._started = True
            self._restore_deadline = monotonic() + 5
            for plugin_id in sorted(self._config.enabled):
                try:
                    self._enable(plugin_id, dict(self._config.enabled), restoring=True)
                except (PluginOperationError, PluginResolutionError) as error:
                    with self._state_lock:
                        if plugin_id in self._entries:
                            entry = self._entries[plugin_id]
                            if entry.state != PluginState.FAILED:
                                entry.state = PluginState.UNAVAILABLE
                                entry.issue = error.issue
                        else:
                            self._orphans[plugin_id] = error.issue
            self._restore_deadline = None

    def enable(self, plugin_id, grants=None, *, expected_revision=None):
        with self._control:
            self._check_mutation(expected_revision)
            self._enable(plugin_id, grants or {})
            return self.snapshot()

    def preview(self, plugin_id, operation, *, permission=None, expected_revision=None):
        with self._control, self._state_lock:
            self._check_mutation(expected_revision)
            if operation == "enable":
                targets = enable_targets(
                    plugin_id,
                    self._registry,
                    self._entries,
                    self._config,
                    self._workers,
                    self._app_version,
                    _problem,
                )
            elif operation in {"disable", "revoke"}:
                if plugin_id not in self._entries and plugin_id not in self._config.enabled:
                    _problem("missing_plugin", plugin_id, "插件未登记")
                if operation == "revoke":
                    entry = self._entries.get(plugin_id)
                    if entry is None or permission not in entry.definition.manifest.permissions:
                        _problem("invalid_grant", plugin_id, "插件没有声明该权限")
                targets = stop_targets(self._affected(plugin_id), self._entries, self._config)
            else:
                _problem("invalid_operation", plugin_id, "管理操作不存在")
            return {
                "revision": self._config.revision,
                "operation": operation,
                "plugin_id": plugin_id,
                "permission": permission.value if permission is not None else None,
                "targets": targets,
            }

    def _enable(self, plugin_id, grants, *, restoring=False):
        deadline = monotonic() + 5
        plan = self._registry.plan_activation([plugin_id], app_version=self._app_version)
        if set(grants) - set(plan.ordered):
            # Restore passes the entire saved set, while an API request is scoped to this plan.
            if not restoring:
                _problem("unexpected_grant", plugin_id, "只能为本次选择及其依赖提供授权")
        desired, prepared = dict(self._config.enabled), []
        permissions = {}
        for owner in plan.ordered:
            entry = self._entries[owner]
            spec = entry.definition.manifest
            selected = tuple(grants.get(owner, desired.get(owner, ())))
            if set(spec.capabilities) - _SUPPORTED or set(spec.permissions) - _PERMISSIONS:
                _problem("unsupported_contribution", owner, "此插件需要尚未实现的宿主接口")
            if (
                any(type(value) is not PluginPermission for value in selected)
                or len(set(selected)) != len(selected)
                or not set(selected) <= set(spec.permissions)
            ):
                _problem("invalid_grant", owner, "授权不能重复或超出插件声明")
            required = required_permissions(spec, entry.definition.required_permissions)
            if not required <= set(selected):
                _problem("permission_required", owner, "启用前需要明确授予所需的数据权限")
            if entry.state == PluginState.RUNNING:
                if set(selected) != entry.lease.permissions:
                    _problem("already_running", owner, "请先停用插件，再调整授权")
            elif self._workers.busy(owner):
                _problem("workers_still_running", owner, "旧任务尚未停止，不能重复启动")
            elif restoring and owner in self._restore_attempted:
                _problem("dependency_failed", owner, "本次启动中依赖已失败，不自动重复尝试")
            permissions[owner] = selected

        if all(self._entries[owner].state == PluginState.RUNNING for owner in plan.ordered):
            return
        try:
            for owner in plan.ordered:
                entry = self._entries[owner]
                if entry.state == PluginState.RUNNING:
                    continue
                self._workers.forget(owner)
                self._generation += 1
                lease = PluginAccessLease(entry.definition.manifest, permissions[owner])
                with self._state_lock:
                    entry.generation, entry.lease = self._generation, lease
                    entry.state, entry.issue = PluginState.STARTING, None
                prepared.append(owner)
                self._restore_attempted.add(owner)
                remaining = min(self._startup_timeout, deadline - monotonic())
                if self._restore_deadline is not None:
                    remaining = min(remaining, self._restore_deadline - monotonic())
                if remaining <= 0:
                    _problem("startup_budget", owner, "插件恢复超过本次启动预算，请手动重试")
                reader = PluginSummaryReader(entry.definition.manifest, self._summary, lease=lease)
                context = PluginContext(
                    owner,
                    reader if PluginPermission.SUMMARY_READ in permissions[owner] else None,
                    PluginGameFiles(self._catalog_files.get(owner), lease)
                    if PluginPermission.FILE_IMPORT in permissions[owner]
                    and PluginCapability.GAME_CATALOG in entry.definition.manifest.capabilities
                    else None,
                )
                result = self._workers.call(
                    owner,
                    entry.generation,
                    lambda e=entry, c=context: _create_contributions(
                        e.definition,
                        c,
                        self._page_validator,
                    ),
                    remaining,
                )
                spec = entry.definition.manifest
                if (
                    type(result) is not PluginContributions
                    or (result.classifiers and PluginCapability.CLASSIFIER not in spec.capabilities)
                    or (result.tasks and PluginCapability.TASK not in spec.capabilities)
                    or (result.analytics and PluginCapability.ANALYTICS not in spec.capabilities)
                    or (result.pages and PluginCapability.PAGE not in spec.capabilities)
                    or any(
                        not set(value.permissions) <= set(spec.permissions)
                        for value in result.analytics
                    )
                    or (
                        result.game_catalog
                        and PluginCapability.GAME_CATALOG not in spec.capabilities
                    )
                    or (
                        result.game_classifier
                        and (
                            PluginCapability.CLASSIFIER not in spec.capabilities
                            or PluginPermission.GAME_CATALOG_READ not in permissions[owner]
                        )
                    )
                ):
                    _problem("invalid_contribution", owner, "插件返回了无效或未声明的贡献")
                with self._state_lock:
                    if entry.state != PluginState.STARTING:
                        raise PluginOperationError(entry.issue)
                    entry.contributions = result
                    entry.classifiers = tuple(
                        PluginClassifier(spec, value, lease=lease) for value in result.classifiers
                    )
                    entry.game_catalog = (
                        PluginGameCatalog(result.game_catalog, lease)
                        if result.game_catalog
                        else None
                    )
                    entry.game_classifier = (
                        PluginGameClassifier(result.game_classifier, lease)
                        if result.game_classifier
                        else None
                    )
                desired[owner] = permissions[owner]
            active = [
                entry
                for entry in self._entries.values()
                if entry.state in {PluginState.STARTING, PluginState.RUNNING}
            ]
            reserve = (
                int(any(entry.classifiers or entry.game_classifier for entry in active))
                + int(any(entry.game_catalog for entry in active))
                + int(any(entry.contributions.analytics for entry in active))
            )
            self._workers.check_capacity(
                sum(len(self._entries[owner].contributions.tasks) for owner in prepared) + reserve
            )
            if not restoring:
                self._save(desired)
        except (PluginOperationError, PluginExecutionError) as error:
            self._withdraw(prepared)
            if isinstance(error, PluginOperationError):
                raise
            _problem(error.code, plugin_id, "插件未能完成启动，旧运行集合保持可用")

        # Only commit contributions after every factory passed and intent was saved.
        for owner in prepared:
            entry = self._entries[owner]
            try:
                for task in entry.contributions.tasks:
                    with self._state_lock:
                        if entry.state != PluginState.STARTING:
                            break
                    self._workers.start(owner, entry.generation, task)
                    with self._state_lock:
                        if entry.state != PluginState.STARTING:
                            self._workers.request_stop(owner)
            except (PluginExecutionError, ValueError):
                self._fault(owner, entry.generation, "worker_start_failed")
            with self._state_lock:
                if entry.state == PluginState.STARTING:
                    entry.state = PluginState.RUNNING

    def _affected(self, plugin_id):
        affected = {plugin_id}
        while True:
            expanded = affected | {
                owner
                for owner, entry in self._entries.items()
                if (
                    owner in self._config.enabled
                    or entry.state
                    in {
                        PluginState.RUNNING,
                        PluginState.STARTING,
                    }
                )
                and any(dep.plugin_id in affected for dep in entry.definition.manifest.dependencies)
            }
            if expanded == affected:
                return affected
            affected = expanded

    def _fault(self, owner, generation, code):
        with self._state_lock:
            entry = self._entries[owner]
            if entry.generation != generation or entry.state not in {
                PluginState.STARTING,
                PluginState.RUNNING,
            }:
                return
            affected = self._affected(owner)
            for target in affected:
                entry = self._entries.get(target)
                if entry is None or entry.state not in {PluginState.STARTING, PluginState.RUNNING}:
                    continue
                if entry.lease:
                    entry.lease.revoke()
                failure = code if target == owner else "dependency_failed"
                entry.state = PluginState.FAILED
                entry.issue = PluginIssue(failure, target, _MESSAGES.get(failure, "插件不可用"))
                entry.classifiers = ()
                entry.game_catalog, entry.game_classifier = None, None
        for target in affected:
            self._workers.request_stop(target)

    def _withdraw(self, owners):
        with self._state_lock:
            for owner in owners:
                entry = self._entries[owner]
                if entry.lease:
                    entry.lease.revoke()
                entry.classifiers = ()
                entry.game_catalog, entry.game_classifier = None, None
                if entry.state != PluginState.FAILED:
                    entry.state = PluginState.DISABLED
        for owner in owners:
            self._workers.request_stop(owner)

    def disable(self, plugin_id, *, cascade=False, expected_revision=None):
        with self._control:
            self._check_mutation(expected_revision)
            if plugin_id not in self._entries and plugin_id not in self._config.enabled:
                _problem("missing_plugin", plugin_id, "插件未登记")
            affected = self._affected(plugin_id)
            if not cascade and affected - {plugin_id}:
                _problem("dependents_active", plugin_id, "请共同停用仍依赖它的插件")
            desired = {
                key: value for key, value in self._config.enabled.items() if key not in affected
            }
            if desired != dict(self._config.enabled):
                self._save(desired)
            with self._state_lock:
                for owner in affected:
                    entry = self._entries.get(owner)
                    if entry is not None:
                        if entry.lease:
                            entry.lease.revoke()
                        entry.state = PluginState.STOPPING
                        entry.classifiers = ()
                        entry.game_catalog, entry.game_classifier = None, None
            for owner in affected:
                self._workers.request_stop(owner)
            deadline = monotonic() + self._stop_timeout
            for owner in affected:
                result = self._workers.wait_stopped(owner, max(0, deadline - monotonic()))
                with self._state_lock:
                    if owner in self._entries:
                        entry = self._entries[owner]
                        entry.state = (
                            PluginState.DISABLED
                            if result == TaskStopResult.STOPPED
                            else PluginState.FAILED
                        )
                        entry.issue = (
                            None
                            if result == TaskStopResult.STOPPED
                            else PluginIssue(
                                "stop_timeout",
                                owner,
                                _MESSAGES["stop_timeout"],
                            )
                        )
                    self._orphans.pop(owner, None)
            return self.snapshot()

    def revoke(self, plugin_id, permission, *, expected_revision=None):
        with self._control:
            entry = self._entries.get(plugin_id)
            if entry is None:
                _problem("missing_plugin", plugin_id, "插件未登记")
            if permission not in entry.definition.manifest.permissions:
                _problem("invalid_grant", plugin_id, "插件没有声明该权限")
            return self.disable(plugin_id, cascade=True, expected_revision=expected_revision)

    def fetch_game_catalog(self, plugin_id):
        with self._state_lock:
            entry = self._entries.get(plugin_id)
            if entry is None:
                _problem("missing_plugin", plugin_id, "游戏资料插件未登记")
            if entry.state != PluginState.RUNNING or entry.game_catalog is None:
                _problem("catalog_inactive", plugin_id, "请先启用游戏资料插件")
            source, generation, lease = entry.game_catalog, entry.generation, entry.lease

        def read():
            try:
                return source.fetch()
            except GameCatalogUnavailable:
                return _CatalogMiss()

        try:
            result = self._workers.call(
                plugin_id, generation, read, self._catalog_timeout, channel="metadata"
            )
        except PluginExecutionError as error:
            if error.code not in {"call_busy", "worker_limit"}:
                self._fault(plugin_id, generation, error.code)
            _problem(error.code, plugin_id, "游戏资料插件暂时无法完成读取")
        lease.require(
            PluginCapability.GAME_CATALOG,
            PluginPermission.FILE_IMPORT,
            PluginPermission.GAME_CATALOG_PROPOSE,
        )
        if isinstance(result, _CatalogMiss):
            with self._state_lock:
                if entry.generation == generation:
                    entry.catalog_issue = PluginIssue(
                        "catalog_unavailable",
                        plugin_id,
                        "Playnite 资料缺失或格式无效，已有资料保留",
                    )
            raise GameCatalogUnavailable("Playnite 资料缺失或格式无效，已有资料保留")
        with self._state_lock:
            if entry.generation == generation:
                entry.catalog_issue = None
        return GameCatalogTicket(plugin_id, generation, result)

    def commit_game_catalog(self, ticket, commit):
        """Host-only final transaction commit, serialized with disable/revoke."""
        with self._state_lock:
            entry = self._entries.get(ticket.owner)
            if (
                entry is None
                or entry.generation != ticket.generation
                or entry.state != PluginState.RUNNING
                or entry.game_catalog is None
            ):
                _problem("catalog_stale", ticket.owner, "游戏资料读取已失效，本次导入已撤回")
            entry.lease.require(
                PluginCapability.GAME_CATALOG,
                PluginPermission.FILE_IMPORT,
                PluginPermission.GAME_CATALOG_PROPOSE,
            )
            commit()

    def read_game_media(self, plugin_id, read):
        """Host presentation compatibility call; not a plugin SDK callback interface."""
        with self._state_lock:
            entry = self._entries.get(plugin_id)
            if entry is None or entry.state != PluginState.RUNNING:
                _problem("catalog_inactive", plugin_id, "游戏资料插件不可用")
            generation, lease = entry.generation, entry.lease

        def checked():
            lease.require(PluginCapability.GAME_CATALOG, PluginPermission.FILE_IMPORT)
            result = read()
            lease.require(PluginCapability.GAME_CATALOG, PluginPermission.FILE_IMPORT)
            return result

        try:
            result = self._workers.call(
                plugin_id, generation, checked, self._catalog_timeout, channel="metadata"
            )
        except PluginExecutionError as error:
            if error.code not in {"call_busy", "worker_limit"}:
                self._fault(plugin_id, generation, error.code)
            raise
        lease.require(PluginCapability.GAME_CATALOG, PluginPermission.FILE_IMPORT)
        return result

    def for_processing(self, catalog=None):
        with self._state_lock:
            ordered = sorted(
                self._entries.items(), key=lambda item: (item[1].definition.priority, item[0])
            )
            # Existing regular plugin proposals precede catalog matching, as before extraction.
            selected = [
                (owner, entry.generation, entry.classifiers, entry.lease)
                for owner, entry in ordered
                if entry.state == PluginState.RUNNING and entry.classifiers
            ] + [
                (owner, entry.generation, (entry.game_classifier,), entry.lease)
                for owner, entry in ordered
                if entry.state == PluginState.RUNNING and entry.game_classifier
            ]
        if any(isinstance(chain[0], PluginGameClassifier) for _, _, chain, _ in selected):
            try:
                catalog = catalog or self._catalog_reader.read()
                if type(catalog) is not GameCatalogSnapshot:
                    raise TypeError("资料读取接口需要不可变快照")
            except Exception:
                for owner, generation, chain, _ in selected:
                    if isinstance(chain[0], PluginGameClassifier):
                        self._fault(owner, generation, "catalog_read_failed")
                selected = [
                    value for value in selected if not isinstance(value[2][0], PluginGameClassifier)
                ]
                catalog = None
        return _ClassifierBatch(self, selected, catalog or GameCatalogSnapshot())

    def classify(self, event):
        return self.for_processing().classify(event)

    def _classify(self, event, selected, catalog, identities, apps):
        if not selected:
            return None
        # Strip host-only fields from ResolvedActivity before passing the canonical event.
        value = ActivityEvent(
            **{name: getattr(event, name) for name in ActivityEvent.__dataclass_fields__}
        )
        deadline = monotonic() + self._call_timeout
        for owner, generation, classifiers, lease in selected:
            if (
                isinstance(classifiers[0], PluginGameClassifier)
                and value.app.casefold() not in apps
            ):
                continue
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            try:

                def propose(chain=classifiers):
                    for classifier in chain:
                        result = (
                            classifier.classify(value, catalog, identities)
                            if isinstance(classifier, PluginGameClassifier)
                            else classifier.classify(value)
                        )
                        if result is not None:
                            return result
                    return None

                result = self._workers.call(owner, generation, propose, remaining)
                lease.require(
                    PluginCapability.CLASSIFIER,
                    PluginPermission.DETAILS_READ,
                    PluginPermission.CLASSIFICATION_PROPOSE,
                )
                if result is not None:
                    return result
            except PluginExecutionError as error:
                if error.code not in {"call_busy", "worker_limit"}:
                    self._fault(owner, generation, error.code)
            except PermissionError:
                pass  # Disabled/revoked while the call was in flight; discard its proposal.
        return None

    def snapshot(self):
        with self._state_lock:
            plugins = []
            for owner, entry in sorted(self._entries.items()):
                spec = entry.definition.manifest
                plugins.append(
                    {
                        "id": owner,
                        "name": spec.name,
                        "version": spec.version,
                        "capabilities": [value.value for value in spec.capabilities],
                        "declared_permissions": [value.value for value in spec.permissions],
                        "dependencies": [
                            {"id": value.plugin_id, "version": value.version_spec}
                            for value in spec.dependencies
                        ],
                        "state": entry.state.value,
                        "enabled": owner in self._config.enabled,
                        "saved_permissions": sorted(
                            value.value for value in self._config.enabled.get(owner, ())
                        ),
                        "permissions": sorted(
                            permission.value for permission in entry.lease.permissions
                        )
                        if entry.lease
                        and entry.state
                        in {
                            PluginState.RUNNING,
                            PluginState.STARTING,
                        }
                        else [],
                        "last_error": None
                        if entry.issue is None
                        else {
                            "code": entry.issue.code,
                            "message": entry.issue.message,
                        },
                        "catalog_error": None
                        if entry.catalog_issue is None
                        else {
                            "code": entry.catalog_issue.code,
                            "message": entry.catalog_issue.message,
                        },
                        "workers": self._workers.snapshot(owner),
                    }
                )
            for owner, issue in sorted(self._orphans.items()):
                plugins.append(
                    {
                        "id": owner,
                        "name": owner,
                        "version": None,
                        "state": PluginState.UNAVAILABLE.value,
                        "enabled": True,
                        "permissions": [],
                        "saved_permissions": sorted(
                            value.value for value in self._config.enabled.get(owner, ())
                        ),
                        "workers": [],
                        "last_error": {"code": issue.code, "message": issue.message},
                    }
                )
            return {
                "revision": self._config.revision,
                "closing": self._closing,
                "configuration_error": None
                if self._config_error is None
                else {
                    "code": self._config_error.code,
                    "message": self._config_error.message,
                },
                "plugins": plugins,
            }

    def close(self):
        with self._control:
            self._closing = True
            self._withdraw(tuple(self._entries))
            drained = self._workers.close(self._stop_timeout)
            with self._state_lock:
                for owner, entry in self._entries.items():
                    if self._workers.busy(owner):
                        entry.state = PluginState.FAILED
                        entry.issue = PluginIssue("stop_timeout", owner, _MESSAGES["stop_timeout"])
            return drained

    def when_drained(self, callback):
        self._workers.when_drained(callback)
