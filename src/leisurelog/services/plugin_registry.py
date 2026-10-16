"""Preview compatible activation order without changing installed or running state."""

from collections.abc import Sequence
from types import MappingProxyType

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from leisurelog.domain.plugins import (
    PLUGIN_API_VERSION,
    PluginActivationPlan,
    PluginIssue,
    PluginManifest,
    PluginResolutionError,
)


def _reject(code: str, plugin_id: str, message: str):
    raise PluginResolutionError(PluginIssue(code, plugin_id, message))


class PluginRegistry:
    def __init__(self, installed: Sequence[PluginManifest]):
        by_id = {}
        for manifest in installed:
            if manifest.plugin_id in by_id:
                raise ValueError(f"插件 ID 冲突：{manifest.plugin_id}")
            by_id[manifest.plugin_id] = manifest
        self.installed = MappingProxyType(by_id)

    def plan_activation(
        self,
        requested: Sequence[str],
        *,
        app_version: str,
        api_version: int = PLUGIN_API_VERSION,
    ) -> PluginActivationPlan:
        host_version = Version(app_version)
        selected = tuple(dict.fromkeys(requested))
        ordered = []
        visiting = []
        completed = set()

        def visit(plugin_id):
            if plugin_id in visiting:
                cycle = " → ".join(visiting[visiting.index(plugin_id):] + [plugin_id])
                _reject("dependency_cycle", plugin_id, f"插件依赖存在循环：{cycle}")
            if plugin_id in completed:
                return
            manifest = self.installed.get(plugin_id)
            if manifest is None:
                _reject("missing_plugin", plugin_id, f"请先安装插件：{plugin_id}")
            if manifest.api_version != api_version:
                _reject("api_incompatible", plugin_id, f"{manifest.name} 与当前插件接口不兼容")
            try:
                if host_version not in SpecifierSet(manifest.requires_app):
                    _reject(
                        "app_incompatible", plugin_id,
                        f"{manifest.name} 需要 LeisureLog {manifest.requires_app}",
                    )
                Version(manifest.version)
            except (InvalidVersion, InvalidSpecifier) as exc:
                _reject("invalid_version", plugin_id, f"{manifest.name} 的版本声明无效：{exc}")
            visiting.append(plugin_id)
            for dependency in manifest.dependencies:
                provider = self.installed.get(dependency.plugin_id)
                if provider is None:
                    _reject(
                        "missing_dependency", plugin_id,
                        f"{manifest.name} 需要先安装：{dependency.plugin_id}",
                    )
                try:
                    compatible = Version(provider.version) in SpecifierSet(dependency.version_spec)
                except (InvalidVersion, InvalidSpecifier) as exc:
                    _reject("invalid_version", plugin_id, f"{manifest.name} 的依赖声明无效：{exc}")
                if not compatible:
                    _reject(
                        "dependency_incompatible", plugin_id,
                        f"{manifest.name} 需要 {dependency.plugin_id} {dependency.version_spec}，"
                        f"已安装 {provider.version}",
                    )
                visit(dependency.plugin_id)
            visiting.pop()
            completed.add(plugin_id)
            ordered.append(plugin_id)

        for plugin_id in selected:
            visit(plugin_id)
        return PluginActivationPlan(
            requested=selected,
            ordered=tuple(ordered),
            implicit_dependencies=tuple(p for p in ordered if p not in selected),
        )
