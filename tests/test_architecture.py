"""Exercise the dependency gate with source that must fail, including relative imports."""

from pathlib import Path

import pytest

from scripts.check_architecture import check_tree


def scan(tmp_path, files, **kwargs):
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return check_tree(tmp_path, legacy_edges=kwargs.pop("legacy_edges", ()), **kwargs)


def test_current_source_obeys_boundaries_and_does_not_expand_recorded_game_coupling():
    findings = check_tree(Path(__file__).resolve().parents[1] / "src")
    assert not findings, "\n".join(map(str, findings))


@pytest.mark.parametrize("name,code,rule,target", [
    ("domain/nested/model.py", "import leisurelog.api.routes", "layer", "api.routes"),
    ("services/nested/job.py", "from ...repositories import sqlite", "layer", "repositories"),
    ("services/nested/job.py", "from ... import repositories", "layer", "repositories"),
    ("services/__init__.py", "from ..repositories.sqlite import Repo", "layer", "sqlite.Repo"),
    ("analytics/nested/report.py", "from httpx import Client", "infrastructure", "httpx"),
    ("domain/model.py", "import sqlite3", "infrastructure", "sqlite3"),
    ("adapters/source.py", "from leisurelog.services.processing import X", "layer", "services"),
    ("repositories/store.py", "from leisurelog.adapters import x", "layer", "adapters"),
])
def test_nested_and_relative_imports_cannot_bypass_layer_rules(tmp_path, name, code, rule, target):
    findings = scan(tmp_path, {f"leisurelog/{name}": "\n" + code})
    assert any(item.rule == rule and target in item.message and item.line == 2 for item in findings)


def test_version_constants_are_allowed_but_root_module_imports_are_not(tmp_path):
    assert not scan(tmp_path, {"leisurelog/api/route.py": "from leisurelog import __version__"})
    findings = scan(tmp_path, {"leisurelog/domain/model.py": "from leisurelog import main"})
    assert any(item.rule == "layer" for item in findings)


@pytest.mark.parametrize("code", [
    "from leisurelog.repositories.sqlite import SQLiteRepository",
    "from leisurelog import main",
    "from leisurelog.domain.models import ActivityEvent",
    "from leisurelog.plugin_api import Repository",
    "from leisurelog.plugin_api import *",
])
def test_plugin_must_use_explicit_public_interface(tmp_path, code):
    findings = scan(tmp_path, {
        "leisurelog/plugin_api.py": '__all__ = ("ActivityEvent",)',
        "leisurelog_plugins/sample/feature.py": code,
    })
    assert any(item.rule == "plugin-core" for item in findings)


def test_public_interface_and_same_plugin_helpers_are_allowed(tmp_path):
    findings = scan(tmp_path, {
        "leisurelog/plugin_api.py": '__all__ = ("ActivityEvent",)',
        "leisurelog_plugins/sample/feature.py": (
            "from leisurelog.plugin_api import ActivityEvent\n"
            "import leisurelog.plugin_api as api\n"
            "from .helpers import helper"
        ),
        "leisurelog_plugins/sample/helpers.py": "def helper(): pass",
    })
    assert not findings


@pytest.mark.parametrize("code,declared", [
    ("from leisurelog_plugins.library.api import Catalog", False),
    ("from leisurelog_plugins.library.internal import Catalog", True),
    ("from ..library import internal", True),
])
def test_cross_plugin_imports_need_declared_dependencies_and_public_api(tmp_path, code, declared):
    findings = scan(tmp_path, {"leisurelog_plugins/analysis/report.py": code},
        plugin_dependencies={
            "leisurelog_plugins.analysis": frozenset({"leisurelog_plugins.library"})
        } if declared else {},
    )
    assert any(item.rule == "plugin-dependency" for item in findings)


def test_declared_dependency_can_expose_its_public_api(tmp_path):
    findings = scan(tmp_path, {
        "leisurelog_plugins/analysis/report.py": "from ..library.api import Catalog",
        "leisurelog_plugins/library/api.py": "class Catalog: pass",
    }, plugin_dependencies={
        "leisurelog_plugins.analysis": frozenset({"leisurelog_plugins.library"}),
    })
    assert not findings


@pytest.mark.parametrize("code", [
    "import threading", "from concurrent import futures", "import sqlite3", "import subprocess",
    "from asyncio import create_task",
])
def test_plugin_cannot_open_its_own_database_or_create_unowned_tasks(tmp_path, code):
    findings = scan(tmp_path, {"leisurelog_plugins/sample/feature.py": code})
    assert any(item.rule == "plugin-infrastructure" for item in findings)


def test_core_cannot_import_plugin_implementation_even_from_composition_root(tmp_path):
    findings = scan(tmp_path, {"leisurelog/main.py": "import leisurelog_plugins.sample"})
    assert any(item.rule == "core-plugin" for item in findings)


def test_cycles_are_detected_with_relative_imports(tmp_path):
    findings = scan(tmp_path, {
        "leisurelog/domain/a.py": "from .b import B",
        "leisurelog/domain/b.py": "from .a import A",
    })
    cycles = [item for item in findings if item.rule == "cycle"]
    assert len(cycles) == 1
    assert "leisurelog.domain.a → leisurelog.domain.b → leisurelog.domain.a" in cycles[0].message


def test_cross_plugin_cycle_is_rejected_even_when_both_dependencies_are_declared(tmp_path):
    findings = scan(tmp_path, {
        "leisurelog_plugins/one/api.py": "from ..two.api import B",
        "leisurelog_plugins/two/api.py": "from ..one.api import A",
    }, plugin_dependencies={
        "leisurelog_plugins.one": frozenset({"leisurelog_plugins.two"}),
        "leisurelog_plugins.two": frozenset({"leisurelog_plugins.one"}),
    })
    assert [item.rule for item in findings] == ["cycle"]


def test_new_game_coupling_fails_instead_of_being_hidden_by_layer_compliance(tmp_path):
    findings = scan(tmp_path, {
        "leisurelog/services/new_feature.py": "from leisurelog.domain.games import GameClassifier",
    })
    assert any(item.rule == "feature-coupling" for item in findings)


@pytest.mark.parametrize("module,allowed", [
    ("game_integration", True), ("api.games", False),
    ("services.processing", False), ("repositories.sqlite", False),
])
def test_only_explicit_game_host_may_assemble_the_catalog(tmp_path, module, allowed):
    findings = scan(tmp_path, {
        "leisurelog/" + module.replace(".", "/") + ".py":
            "from leisurelog.repositories.games import SQLiteGameCatalog",
    })
    assert bool(findings) != allowed


def test_legacy_exception_must_be_removed_after_refactor(tmp_path):
    edges = {("leisurelog.services.processing", "leisurelog.domain.games.GameClassifier")}
    path = "leisurelog/services/processing.py"
    assert not scan(tmp_path, {path: "from leisurelog.domain.games import GameClassifier"},
        legacy_edges=edges,
    )
    findings = scan(
        tmp_path, {path: "from leisurelog.domain.games import Game"}, legacy_edges=edges,
    )
    assert [item.rule for item in findings] == ["stale-exception"]


def test_checker_never_executes_scanned_code(tmp_path):
    findings = scan(tmp_path, {
        "leisurelog_plugins/sample/feature.py": "raise RuntimeError('must not execute')",
    })
    assert not findings


def test_invalid_relative_import_and_empty_scan_fail_closed(tmp_path):
    assert [item.rule for item in check_tree(tmp_path, legacy_edges=())] == ["empty-source"]
    findings = scan(tmp_path, {"leisurelog/domain/model.py": "from .... import escaped"})
    assert [item.rule for item in findings] == ["parse"]
