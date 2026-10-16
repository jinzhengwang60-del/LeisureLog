# Only explicit public resources are included. Never collect .env, data, outputs or screenshots.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
stage = root / "build" / "desktop-resources"
datas = collect_data_files("leisurelog")
datas += collect_data_files("leisurelog_plugins.game_analysis")
datas += copy_metadata("leisurelog", recursive=True)
datas += [
    (str(root / "config/rules.yaml"), "config"),
    (str(root / "packaging/defaults/playnite-processes.yaml"), "packaging/defaults"),
    (str(root / "migrations"), "migrations"),
    (str(root / "integrations/playnite/LeisureLog.psm1"), "integrations/playnite"),
    (str(root / "integrations/playnite/extension.yaml"), "integrations/playnite"),
    (str(stage / "third-party"), "third-party"),
]
a = Analysis(
    [str(root / "packaging/desktop_entry.py")],
    pathex=[str(root / "src")],
    binaries=[], datas=datas,
    hiddenimports=[
        "pystray._win32", "sqlalchemy.dialects.sqlite.pysqlite", "leisurelog_plugins.playnite",
        "leisurelog_plugins.game_analysis",
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["tkinter", "numpy", "pandas", "scipy", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="LeisureLog", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    icon=str(stage / "LeisureLog.ico"),
    version=str(stage / "version.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LeisureLog")
