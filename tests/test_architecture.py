import ast
from pathlib import Path


def test_domain_and_services_dependency_boundaries():
    root = Path(__file__).resolve().parents[1] / "src/leisurelog"
    for layer in ["domain", "services", "analytics"]:
        for file in (root / layer).glob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imports.append(node.module or "")
                elif isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
            for name in imports:
                assert name.split(".")[0] not in {"sqlalchemy", "fastapi", "httpx", "yaml"}, file
                if name.startswith("leisurelog."):
                    assert name.split(".")[1] in {"domain", layer}, (file, name)
