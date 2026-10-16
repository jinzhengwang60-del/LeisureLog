"""Metadata-only operation plans; never build a plugin or change stored intent."""

from leisurelog.domain.plugin_runtime import PluginState
from leisurelog.services.plugin_policy import (
    SUPPORTED_CAPABILITIES,
    SUPPORTED_PERMISSIONS,
    required_permissions,
)


def enable_targets(plugin_id, registry, entries, config, workers, app_version, problem):
    plan = registry.plan_activation([plugin_id], app_version=app_version)
    targets = []
    for owner in plan.ordered:
        entry = entries[owner]
        manifest = entry.definition.manifest
        if set(manifest.capabilities) - SUPPORTED_CAPABILITIES or (
            set(manifest.permissions) - SUPPORTED_PERMISSIONS
        ):
            problem("unsupported_contribution", owner, "此插件需要尚未实现的宿主接口")
        required = required_permissions(manifest, entry.definition.required_permissions)
        if not required <= set(manifest.permissions):
            problem("permission_required", owner, "插件声明缺少必要权限，当前无法启用")
        running = entry.state == PluginState.RUNNING
        if not running and workers.busy(owner):
            problem("workers_still_running", owner, "旧任务尚未停止，暂时不能重新启用")
        selected = (
            entry.lease.permissions
            if running
            else config.enabled.get(
                owner,
                manifest.permissions,
            )
        )
        targets.append(
            {
                "id": owner,
                "name": manifest.name,
                "state": entry.state.value,
                "already_running": running,
                "declared_permissions": [value.value for value in manifest.permissions],
                "required_permissions": sorted(value.value for value in required),
                "default_grants": [
                    value.value for value in manifest.permissions if value in selected
                ],
            }
        )
    return targets


def stop_targets(affected, entries, config):
    return [
        {
            "id": owner,
            "name": entries[owner].definition.manifest.name if owner in entries else owner,
            "state": entries[owner].state.value
            if owner in entries
            else PluginState.UNAVAILABLE.value,
            "enabled": owner in config.enabled,
        }
        for owner in sorted(affected)
    ]
