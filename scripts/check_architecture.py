"""Check static imports without executing application or plugin code.

Run from the repository root: python scripts/check_architecture.py
Dynamic imports and system permissions require a separate runtime boundary.
"""

import argparse
import ast
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path

LAYERS = {
    "domain": {"domain"},
    "services": {"domain", "services"},
    "analytics": {"domain", "analytics"},
    "adapters": {"domain", "adapters"},
    "repositories": {"domain", "repositories"},
    "api": {"domain", "adapters", "services", "repositories", "analytics", "api"},
    "plugin_api": {"domain"},
}
PURE_LAYERS = {"domain", "services", "analytics"}
INFRA_IMPORTS = {"sqlalchemy", "sqlite3", "fastapi", "httpx", "yaml", "requests"}
PLUGIN_FORBIDDEN = {
    "sqlalchemy", "sqlite3", "fastapi", "threading", "multiprocessing", "asyncio",
    "concurrent.futures", "subprocess",
}
PLUGIN_NAMESPACE = "leisurelog_plugins"
PUBLIC_API = "leisurelog.plugin_api"
CORE_CONSTANTS = {"leisurelog.__version__", "leisurelog.DATABASE_REVISION"}

# Existing feature coupling is recorded exactly, not waived for entire directories.
# Remove an edge here when the corresponding import is removed from the source.
LEGACY_FEATURE_EDGES = frozenset()
# A reviewed host composition point, not a waiver for business or API modules.
HOST_FEATURE_EDGES = frozenset({
    ("leisurelog.game_integration", "leisurelog.repositories.games"),
    ("leisurelog.analysis_integration", "leisurelog.repositories.game_views"),
    ("leisurelog.repositories.game_views", "leisurelog.repositories.game_preferences"),
    ("leisurelog.repositories.game_preferences", "leisurelog.repositories.game_statistics"),
})
FEATURE_MODULES = {
    "leisurelog.adapters.playnite", "leisurelog.api.games",
    "leisurelog.api.game_preferences", "leisurelog.repositories.games",
    "leisurelog.repositories.game_views", "leisurelog.repositories.game_preferences",
    "leisurelog.repositories.game_statistics", "leisurelog.analytics.games",
    "leisurelog.analytics.game_preferences", "leisurelog.services.game_types",
}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    rule: str
    message: str

    def __str__(self):
        return f"{self.path}:{self.line}: [{self.rule}] {self.message}"


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    line: int


def _inside(name: str, namespace: str) -> bool:
    return name == namespace or name.startswith(namespace + ".")


def _plugin_owner(name: str) -> str | None:
    if not _inside(name, PLUGIN_NAMESPACE):
        return None
    return ".".join(name.split(".")[:2])


def _layer(name: str) -> str:
    parts = name.split(".")
    return parts[1] if parts[0] == "leisurelog" and len(parts) > 1 else ""


def _imports(tree: ast.AST, module: str, package: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield ImportEdge(module, alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = resolve_name("." * node.level + base, package)
            for alias in node.names:
                yield ImportEdge(module, f"{base}.{alias.name}", node.lineno)


def _public_exports(tree: ast.AST) -> frozenset[str]:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if type(value) in (tuple, list) and all(type(name) is str for name in value):
                return frozenset(value)
    raise ValueError("公共接口必须使用显式的 __all__ 字符串列表")


def _feature_target(target: str) -> str | None:
    for module in sorted(FEATURE_MODULES):
        if _inside(target, module):
            return module
    # Import the data type explicitly; importing the module can expose its classifier.
    if target in {"leisurelog.domain.games", "leisurelog.domain.games.*"}:
        return "leisurelog.domain.games.GameClassifier"
    if _inside(target, "leisurelog.domain.games.GameClassifier"):
        return "leisurelog.domain.games.GameClassifier"
    return None


def _cycles(graph: dict[str, set[str]]):
    visited, active, stack = set(), set(), []
    found = set()

    def visit(module):
        visited.add(module)
        active.add(module)
        stack.append(module)
        for target in sorted(graph[module]):
            if target in active:
                ring = tuple(stack[stack.index(target):])
                canonical = min(ring[index:] + ring[:index] for index in range(len(ring)))
                found.add(canonical)
            elif target not in visited:
                visit(target)
        stack.pop()
        active.remove(module)

    for module in sorted(graph):
        if module not in visited:
            visit(module)
    return sorted(found)


def check_tree(
    source_root: Path,
    *,
    legacy_edges=LEGACY_FEATURE_EDGES,
    plugin_dependencies: dict[str, frozenset[str]] | None = None,
) -> list[Finding]:
    """Scan one source tree. Dependency keys are package names assigned by the host."""
    findings, modules, edges = [], {}, []
    dependencies = plugin_dependencies or {}
    exports = frozenset()
    for path in sorted(source_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(source_root).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        module = ".".join(parts)
        if not module:
            continue
        modules[module] = path
        package = module if is_package else module.rpartition(".")[0]
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            edges.extend(_imports(tree, module, package))
            if module == PUBLIC_API:
                exports = _public_exports(tree)
        except (SyntaxError, ImportError, ValueError) as error:
            findings.append(Finding(path, getattr(error, "lineno", 1), "parse", str(error)))

    if not modules:
        findings.append(Finding(source_root, 1, "empty-source", "没有找到 Python 源码"))
        return findings

    observed_legacy = set()
    graph = {module: set() for module in modules}
    for edge in edges:
        path, target, layer = modules[edge.source], edge.target, _layer(edge.source)

        def reject(rule, message):
            findings.append(Finding(path, edge.line, rule, message))

        owner, target_owner = _plugin_owner(edge.source), _plugin_owner(target)
        if owner:
            if _inside(target, "leisurelog"):
                name = target.removeprefix(PUBLIC_API + ".")
                if target != PUBLIC_API and not (
                    target.startswith(PUBLIC_API + ".") and name in exports
                ):
                    reject("plugin-core", f"插件只能导入公共接口，不能导入 {target}")
            if target_owner and target_owner != owner:
                if target_owner not in dependencies.get(owner, ()) or not _inside(
                    target, target_owner + ".api"
                ):
                    reject("plugin-dependency", f"跨插件调用需要已声明的公共 api：{target}")
            if any(_inside(target, forbidden) for forbidden in PLUGIN_FORBIDDEN):
                reject("plugin-infrastructure", f"此资源必须由宿主管理：{target}")
        elif _inside(edge.source, "leisurelog") and target_owner:
            reject("core-plugin", f"核心不能直接导入具体插件：{target}")

        is_api_constant = layer == "api" and target in CORE_CONSTANTS
        if layer in LAYERS and _inside(target, "leisurelog") and not is_api_constant:
            if _layer(target) not in LAYERS[layer]:
                reject("layer", f"{layer} 不能依赖 {target}")
        if layer in PURE_LAYERS and target.split(".")[0] in INFRA_IMPORTS:
            reject("infrastructure", f"{layer} 不能直接使用基础设施库 {target}")

        feature = _feature_target(target)
        if _inside(edge.source, "leisurelog") and feature:
            pair = (edge.source, feature)
            if pair in legacy_edges:
                observed_legacy.add(pair)
            elif pair in HOST_FEATURE_EDGES:
                pass
            else:
                reject("feature-coupling", f"新增了具体游戏实现依赖：{target}")

        # Imported attributes resolve to their defining module when it exists in this tree.
        parent = target
        while parent and parent not in modules:
            parent = parent.rpartition(".")[0]
        if parent:
            graph[edge.source].add(parent)

    for source, target in sorted(set(legacy_edges) - observed_legacy):
        findings.append(Finding(
            modules.get(source, source_root), 1, "stale-exception",
            f"删除已不需要的旧耦合例外：{source} → {target}",
        ))
    for ring in _cycles(graph):
        findings.append(Finding(
            modules[ring[0]], 1, "cycle", "循环导入：" + " → ".join((*ring, ring[0])),
        ))
    return sorted(findings, key=lambda finding: (str(finding.path), finding.line, finding.rule))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "src")
    args = parser.parse_args()
    for finding in (findings := check_tree(args.source)):
        print(finding)
    if findings:
        print(f"架构检查失败：{len(findings)} 个问题")
        return 1
    print("架构检查通过：分层、静态插件边界、循环依赖与旧耦合例外")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
