"""Shared activation policy for execution and read-only management previews."""

from leisurelog.domain.plugins import PluginCapability as Capability
from leisurelog.domain.plugins import PluginPermission as Permission

SUPPORTED_CAPABILITIES = frozenset(
    {
        Capability.ANALYTICS,
        Capability.CLASSIFIER,
        Capability.TASK,
        Capability.GAME_CATALOG,
        Capability.PAGE,
    }
)
SUPPORTED_PERMISSIONS = frozenset(
    {
        Permission.SUMMARY_READ,
        Permission.DETAILS_READ,
        Permission.CLASSIFICATION_PROPOSE,
        Permission.GAME_CATALOG_READ,
        Permission.GAME_CATALOG_PROPOSE,
        Permission.FILE_IMPORT,
        Permission.GAME_STATISTICS_READ,
        Permission.GAME_TYPES_WRITE,
    }
)


def required_permissions(manifest, extra=()):
    required = set(extra)
    if Capability.ANALYTICS in manifest.capabilities:
        required.add(Permission.SUMMARY_READ)
    if Capability.CLASSIFIER in manifest.capabilities:
        required.update({Permission.DETAILS_READ, Permission.CLASSIFICATION_PROPOSE})
    if Capability.GAME_CATALOG in manifest.capabilities:
        required.update({Permission.FILE_IMPORT, Permission.GAME_CATALOG_PROPOSE})
    return frozenset(required)
