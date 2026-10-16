"""Read descriptive JSON only; never import code specified by a manifest."""

import json
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from leisurelog.domain.plugins import (
    PluginCapability,
    PluginDependency,
    PluginManifest,
    PluginPermission,
)


class DependencySchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plugin_id: str
    version_spec: str


class ManifestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int = Field(ge=1)
    plugin_id: str
    name: str
    version: str
    requires_app: str
    api_version: int = Field(ge=1)
    capabilities: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    dependencies: list[DependencySchema] = Field(default_factory=list)


def _unique_keys(pairs):
    values = {}
    for key, value in pairs:
        if key in values:
            raise ValueError(f"插件描述字段重复：{key}")
        values[key] = value
    return values


def parse_plugin_manifest(data: str | bytes) -> PluginManifest:
    try:
        payload = json.loads(data, object_pairs_hook=_unique_keys)
        schema = ManifestSchema.model_validate(payload)
        if schema.schema_version != 1:
            raise ValueError("不支持这个插件描述格式版本")
        Version(schema.version)
        SpecifierSet(schema.requires_app)
        for dependency in schema.dependencies:
            SpecifierSet(dependency.version_spec)
        return PluginManifest(
            plugin_id=schema.plugin_id,
            name=schema.name,
            version=schema.version,
            requires_app=schema.requires_app,
            api_version=schema.api_version,
            capabilities=tuple(PluginCapability(v) for v in schema.capabilities),
            permissions=tuple(PluginPermission(v) for v in schema.permissions),
            dependencies=tuple(
                PluginDependency(d.plugin_id, d.version_spec) for d in schema.dependencies
            ),
        )
    except (ValidationError, InvalidSpecifier, InvalidVersion, ValueError) as exc:
        raise ValueError(f"插件描述无效：{exc}") from exc


def read_plugin_manifest(path: Path) -> PluginManifest:
    return parse_plugin_manifest(path.read_text(encoding="utf-8-sig"))
