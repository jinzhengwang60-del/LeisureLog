"""Build a wheel from public source and smoke-test it on fresh synthetic SQLite.

This does not install into the user's environment, rebuild an EXE, start the
daily service or read an existing activity database. Output stays in outputs/.
"""

import argparse
import ast
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    f"game-{page}.{extension}"
    for page in ("statistics", "preferences")
    for extension in ("html", "js", "css")
}
ASSETS.add("game-access.js")
MANAGER_ASSETS = {"plugins.html", "plugins.css", "plugins.js", "plugin-controls.js"}
SMOKE = r"""
import json, os, re, sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import leisurelog.main
from leisurelog.config import Settings

root, unpacked, data = map(Path, sys.argv[1:])
assert Path(leisurelog.main.__file__).resolve().is_relative_to(unpacked.resolve())
data.mkdir()
url = 'sqlite:///' + (data / 'activity.db').as_posix()
os.environ['LEISURELOG_DATABASE_URL'] = url
config = Config(str(root / 'alembic.ini'))
config.attributes['database_url'] = url
command.upgrade(config, 'head')
rules = data / 'rules.yaml'
rules.write_text('rules: []\n', encoding='utf-8')
settings = Settings(database_url=url, rules_path=rules,
                    plugin_state_path=data / 'plugin-state.json',
                    playnite_export_path=data / 'missing.json',
                    playnite_bindings_path=data / 'missing.yaml',
                    auto_sync_enabled=False, auto_backup_days=0)
resources = set()
app = leisurelog.main.create_app(settings, SimpleNamespace(fetch=lambda *args: []))
with TestClient(app) as client:
    assert client.get('/health').json()['database_revision'] == '0013'
    assert len(client.get('/api/plugin-navigation').json()['pages']) == 2
    manager = client.get('/plugins')
    manager.raise_for_status()
    assert '插件管理' in manager.text
    assert manager.headers['cache-control'] == 'no-store'
    for resource in re.findall(r'(?:src|href)="(/static/[^\"]+)"', manager.text):
        client.get(resource).raise_for_status()
        resources.add(resource.split('?')[0])
    assert client.get('/api/plugins/leisurelog.game-analysis/plan').json()['targets']
    client.get('/static/plugin-controls.js').raise_for_status()
    resources.add('/static/plugin-controls.js')
    for page in ('/games', '/game-preferences'):
        response = client.get(page)
        response.raise_for_status()
        assert 'href="/plugins"' in response.text
        for resource in re.findall(r'(?:src|href)="(/plugin-assets/[^\"]+)"', response.text):
            client.get(resource).raise_for_status()
            resources.add(resource.split('?')[0])
    client.get('/api/game-statistics').raise_for_status()
    client.get('/plugin-assets/leisurelog.game-analysis/game-access.js').raise_for_status()
    resources.add('/plugin-assets/leisurelog.game-analysis/game-access.js')
    client.get('/api/game-preferences?start=2026-01-01&end=2026-12-31').raise_for_status()
    backup = client.post('/api/storage/backups')
    backup.raise_for_status()
    with ZipFile(BytesIO(client.get(backup.json()['archive_url']).content)) as archive:
        assert json.loads(archive.read('config/plugin-state.json'))['version'] == 1
print(json.dumps({'wheel_import': True, 'pages': 3, 'manager_plan': True,
                  'config_snapshot': True, 'served_resources': sorted(resources),
                  'schema': '0013'}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "outputs").resolve()) or output.exists():
        parser.error("Output must be a fresh directory under this checkout's outputs/")
    output.mkdir(parents=True)
    syntax_files = [
        *ROOT.joinpath("src").rglob("*.py"),
        *ROOT.joinpath("tests").rglob("*.py"),
        *ROOT.joinpath("scripts").glob("*.py"),
        ROOT / "packaging/LeisureLog.spec",
    ]
    for path in syntax_files:
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path), feature_version=(3, 11))
    stage = output / "source"
    shutil.copytree(
        ROOT / "src",
        stage / "src",
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.egg-info",
        ),
    )
    for name in ("pyproject.toml", "README.md"):
        shutil.copyfile(ROOT / name, stage / name)
    previous = Path.cwd()
    build_log = io.StringIO()
    try:
        os.chdir(stage)
        from setuptools.build_meta import build_wheel

        with contextlib.redirect_stdout(build_log), contextlib.redirect_stderr(build_log):
            wheel = output / build_wheel(str(output))
    finally:
        os.chdir(previous)
        (output / "build.log").write_text(build_log.getvalue(), encoding="utf-8")
    unpacked = output / "wheel"
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert {"leisurelog_plugins/game_analysis/static/" + asset for asset in ASSETS} <= names
        assert not {"leisurelog/api/static/" + asset for asset in ASSETS} & names
        assert "leisurelog/api/static/plugin-navigation.js" in names
        assert {"leisurelog/api/static/" + asset for asset in MANAGER_ASSETS} <= names
        for name in names:
            assert (unpacked / name).resolve().is_relative_to(unpacked.resolve())
        archive.extractall(unpacked)
    result = subprocess.run(
        [sys.executable, "-B", "-c", SMOKE, str(ROOT), str(unpacked), str(output / "smoke-data")],
        cwd=output,
        env={**os.environ, "PYTHONPATH": str(unpacked), "PYTHONUTF8": "1"},
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=60,
    )
    (output / "smoke.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(result.stderr + result.stdout)
    report = {
        "python311_syntax_files": len(syntax_files),
        "wheel": wheel.name,
        "assets_relocated": len(ASSETS),
        "manager_assets": len(MANAGER_ASSETS),
        "smoke": json.loads(result.stdout),
        "exe_rebuilt": False,
        "scope": "public source and synthetic data only",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
