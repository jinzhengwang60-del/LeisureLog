"""Plugin preflight must reject incompatible selections before any state change."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from leisurelog.adapters.plugin_manifest import parse_plugin_manifest, read_plugin_manifest
from leisurelog.domain.plugins import PluginDependency, PluginResolutionError
from leisurelog.services.plugin_registry import PluginRegistry

EXAMPLES = Path(__file__).resolve().parents[1] / "integrations/plugins/examples"


@pytest.fixture
def manifests():
    return {
        key: read_plugin_manifest(EXAMPLES / f"{key}.json")
        for key in ("game-library", "game-analysis", "theme-pack")
    }


def test_selection_includes_required_installed_dependency_without_mutating_catalog(manifests):
    registry = PluginRegistry(list(manifests.values()))
    before = tuple(registry.installed)
    plan = registry.plan_activation(["leisurelog.game-analysis"], app_version="0.5.0a1")
    assert plan.ordered == ("leisurelog.game-library", "leisurelog.game-analysis")
    assert plan.implicit_dependencies == ("leisurelog.game-library",)
    assert tuple(registry.installed) == before
    assert registry.plan_activation([], app_version="0.5.0a1").ordered == ()


def test_missing_dependency_rejects_whole_selection_without_partial_activation(manifests):
    registry = PluginRegistry([manifests["theme-pack"], manifests["game-analysis"]])
    with pytest.raises(PluginResolutionError) as error:
        registry.plan_activation(
            ["leisurelog.theme-pack", "leisurelog.game-analysis"], app_version="0.5.0a1"
        )
    assert error.value.issue.code == "missing_dependency"
    assert len(registry.installed) == 2
    assert registry.plan_activation(["leisurelog.theme-pack"], app_version="0.5.0a1").ordered == (
        "leisurelog.theme-pack",
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ({"version": "0.2.0"}, "dependency_incompatible"),
        ({"api_version": 2}, "api_incompatible"),
        ({"requires_app": ">=0.6"}, "app_incompatible"),
    ],
)
def test_installed_dependency_must_meet_version_and_host_contract(manifests, change, code):
    provider = replace(manifests["game-library"], **change)
    registry = PluginRegistry([provider, manifests["game-analysis"]])
    with pytest.raises(PluginResolutionError) as error:
        registry.plan_activation(["leisurelog.game-analysis"], app_version="0.5.0a1")
    assert error.value.issue.code == code


def test_dependency_cycle_is_explained_without_returning_a_partial_plan(manifests):
    provider = replace(
        manifests["game-library"],
        dependencies=(PluginDependency("leisurelog.game-analysis", ">=0.1,<0.2"),),
    )
    registry = PluginRegistry([provider, manifests["game-analysis"]])
    with pytest.raises(PluginResolutionError) as error:
        registry.plan_activation(["leisurelog.game-analysis"], app_version="0.5.0a1")
    assert error.value.issue.code == "dependency_cycle"
    assert "leisurelog.game-analysis → leisurelog.game-library" in str(error.value)


def test_incompatible_unselected_plugin_does_not_block_a_working_theme(manifests):
    incompatible = replace(manifests["game-analysis"], api_version=99)
    registry = PluginRegistry([incompatible, manifests["theme-pack"]])
    assert registry.plan_activation(
        ["leisurelog.theme-pack", "leisurelog.theme-pack"], app_version="0.5.0a1"
    ).ordered == ("leisurelog.theme-pack",)


def test_duplicate_installed_plugin_ids_are_rejected(manifests):
    with pytest.raises(ValueError, match="ID 冲突"):
        PluginRegistry([manifests["theme-pack"], manifests["theme-pack"]])


def test_first_plugin_contract_cannot_be_activated_in_the_v04_baseline(manifests):
    with pytest.raises(PluginResolutionError) as error:
        PluginRegistry(list(manifests.values())).plan_activation(
            ["leisurelog.theme-pack"], app_version="0.4.0b1"
        )
    assert error.value.issue.code == "app_incompatible"


@pytest.mark.parametrize(
    "field,value",
    [
        ("plugin_id", "../core"),
        ("plugin_id", "core.session"),
        ("version", "not-a-version"),
        ("requires_app", "not-a-specifier"),
        ("api_version", True),
        ("schema_version", True),
        ("schema_version", 2),
        ("capabilities", ["database-write"]),
        ("permissions", ["database.write"]),
        ("permissions", ["network.request", "network.request"]),
        ("entry_point", "untrusted_module:execute"),
        ("trusted", True),
    ],
)
def test_manifest_rejects_unsafe_or_ambiguous_descriptions(field, value):
    payload = json.loads((EXAMPLES / "theme-pack.json").read_text(encoding="utf-8"))
    payload[field] = value
    with pytest.raises(ValueError, match="插件描述无效"):
        parse_plugin_manifest(json.dumps(payload))


def test_duplicate_json_keys_cannot_hide_a_different_permission_request():
    with pytest.raises(ValueError, match="字段重复"):
        parse_plugin_manifest('{"permissions":[],"permissions":["network.request"]}')


@pytest.mark.parametrize("target", ["leisurelog.game-library", "leisurelog.other"])
def test_manifest_rejects_self_dependency_or_duplicate_dependency(target):
    payload = json.loads((EXAMPLES / "game-library.json").read_text(encoding="utf-8"))
    payload["dependencies"] = [
        {"plugin_id": target, "version_spec": ">=0.1"},
        {"plugin_id": target, "version_spec": ">=0.2"},
    ]
    with pytest.raises(ValueError, match="自身或重复"):
        parse_plugin_manifest(json.dumps(payload))


def test_invalid_dependency_specifier_is_reported_before_planning():
    payload = json.loads((EXAMPLES / "game-analysis.json").read_text(encoding="utf-8"))
    payload["dependencies"][0]["version_spec"] = "invalid"
    with pytest.raises(ValueError, match="插件描述无效"):
        parse_plugin_manifest(json.dumps(payload))
