"""Checked calls for official plugins. These wrappers are not a Python sandbox."""

from dataclasses import replace
from threading import RLock

from leisurelog.domain.game_catalog import (
    GameCatalogFiles,
    GameCatalogImport,
    GameCatalogSnapshot,
    GameMatch,
)
from leisurelog.domain.models import ActivityEvent, Classification
from leisurelog.domain.plugin_contracts import ActivitySummary, SummaryQuery, SummaryReader
from leisurelog.domain.plugins import PluginCapability, PluginManifest, PluginPermission
from leisurelog.domain.ports import Classifier


class PluginAccessDenied(PermissionError):
    pass


class PluginAccessLease:
    """A fresh, revocable grant per activation; old readers never regain access."""

    def __init__(self, manifest: PluginManifest, permissions):
        self.manifest = manifest
        self.permissions = frozenset(permissions)
        if not self.permissions <= set(manifest.permissions):
            raise ValueError("授权不能超出描述声明")
        self._active = True
        self._lock = RLock()

    def revoke(self):
        with self._lock:
            self._active = False

    def require(self, capability: PluginCapability, *permissions):
        with self._lock:
            missing = [value.value for value in permissions if value not in self.permissions]
            if capability not in self.manifest.capabilities:
                missing.insert(0, capability.value)
            if not self._active or missing:
                raise PluginAccessDenied(f"{self.manifest.plugin_id} 的接口未获授权或已撤销")


class PluginSummaryReader:
    """Only a summary provider is injected; no database or detail reader is exposed."""

    def __init__(self, manifest: PluginManifest, provider: SummaryReader, *, lease=None):
        self._lease = lease or PluginAccessLease(manifest, manifest.permissions)
        self._provider = provider

    def read(self, query: SummaryQuery) -> ActivitySummary:
        self._lease.require(PluginCapability.ANALYTICS, PluginPermission.SUMMARY_READ)
        if type(query) is not SummaryQuery:
            raise TypeError("插件汇总接口需要 SummaryQuery")
        result = self._provider.read(query)
        self._lease.require(PluginCapability.ANALYTICS, PluginPermission.SUMMARY_READ)
        if type(result) is not ActivitySummary:
            raise TypeError("汇总提供者必须返回 ActivitySummary，不能返回活动详情")
        return result


class PluginClassifier:
    """The host labels proposals. Existing ClassificationPipeline keeps manual priority."""

    def __init__(self, manifest: PluginManifest, classifier: Classifier, *, lease=None):
        self._manifest = manifest
        self._lease = lease or PluginAccessLease(manifest, manifest.permissions)
        self._classifier = classifier

    def classify(self, event: ActivityEvent) -> Classification | None:
        self._lease.require(
            PluginCapability.CLASSIFIER,
            PluginPermission.DETAILS_READ,
            PluginPermission.CLASSIFICATION_PROPOSE,
        )
        if type(event) is not ActivityEvent:
            raise TypeError("分类接口需要统一 ActivityEvent")
        result = self._classifier.classify(event)
        self._lease.require(
            PluginCapability.CLASSIFIER,
            PluginPermission.DETAILS_READ,
            PluginPermission.CLASSIFICATION_PROPOSE,
        )
        if result is None:
            return None
        if type(result) is not Classification:
            raise TypeError("分类器必须返回 Classification 或 None")
        if (
            type(result.category) is not str
            or not result.category.strip()
            or (result.content is not None and type(result.content) is not str)
            or type(result.tags) not in (tuple, list)
            or any(type(tag) is not str or not tag.strip() for tag in result.tags)
        ):
            raise ValueError("分类建议包含无效字段")
        return replace(
            result,
            tags=tuple(result.tags),
            origin=f"plugin:{self._manifest.plugin_id}@{self._manifest.version}",
        )


class PluginGameFiles:
    def __init__(self, provider, lease):
        self._provider, self._lease = provider, lease

    def read(self):
        self._lease.require(PluginCapability.GAME_CATALOG, PluginPermission.FILE_IMPORT)
        if self._provider is None:
            raise ValueError("宿主没有提供游戏文件接口")
        result = self._provider.read()
        self._lease.require(PluginCapability.GAME_CATALOG, PluginPermission.FILE_IMPORT)
        if type(result) is not GameCatalogFiles:
            raise TypeError("文件接口只能返回固定的游戏导出与绑定文本")
        return GameCatalogFiles(result.export_json, result.bindings_yaml)


class PluginGameCatalog:
    def __init__(self, source, lease):
        self._source, self._lease = source, lease

    def fetch(self):
        self._lease.require(
            PluginCapability.GAME_CATALOG,
            PluginPermission.FILE_IMPORT,
            PluginPermission.GAME_CATALOG_PROPOSE,
        )
        result = self._source.fetch()
        self._lease.require(
            PluginCapability.GAME_CATALOG,
            PluginPermission.FILE_IMPORT,
            PluginPermission.GAME_CATALOG_PROPOSE,
        )
        if type(result) is not GameCatalogImport:
            raise TypeError("游戏资料贡献必须返回 GameCatalogImport")
        # Revalidate even a forged/mutated dataclass before it reaches persistence.
        return GameCatalogImport(result.raw_json, result.games)


class PluginGameClassifier:
    def __init__(self, classifier, lease):
        self._classifier, self._lease = classifier, lease

    def classify(self, event, catalog: GameCatalogSnapshot, identities):
        self._require()
        result = self._classifier.classify(event, catalog)
        self._require()
        if result is None:
            return None
        if type(result) is not GameMatch:
            raise TypeError("游戏匹配只能提出 GameMatch 或 None")
        game = identities.get(GameMatch(result.game_id).game_id)
        if game is None or not game.installed:
            raise ValueError("游戏匹配不能引用未知或未安装的资料")
        # Preserve the existing stable ID for rename/removal statistics and rollback.
        # Neither the origin, name nor tags are trusted from a plugin proposal.
        return Classification("game", game.name, game.tags, f"{catalog.namespace}:{game.id}")

    def _require(self):
        self._lease.require(
            PluginCapability.CLASSIFIER,
            PluginPermission.DETAILS_READ,
            PluginPermission.CLASSIFICATION_PROPOSE,
            PluginPermission.GAME_CATALOG_READ,
        )
