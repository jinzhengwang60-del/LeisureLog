"""Build a Windows bundle and optional installer with explicit inputs and a file manifest."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def build_resources(version):
    from PIL import Image, ImageDraw

    stage = ROOT / "build/desktop-resources"
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "installer-notice.txt").write_text(
        (ROOT / "packaging/installer-notice.txt").read_text(encoding="utf-8"),
        encoding="utf-8-sig",
    )
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 248, 248), 56, fill="#498578")
    draw.ellipse((48, 48, 208, 208), outline="white", width=12)
    draw.line((128, 75, 128, 128, 174, 153), fill="white", width=12)
    image.save(stage / "LeisureLog.ico", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    (stage / "version.txt").write_text(
        "VSVersionInfo(ffi=FixedFileInfo(filevers=(0,4,0,0), prodvers=(0,4,0,0), "
        "mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)), "
        "kids=[StringFileInfo([StringTable('040904B0', ["
        "StringStruct('CompanyName','LeisureLog'), "
        "StringStruct('FileDescription','LeisureLog local activity tracker'), "
        f"StringStruct('FileVersion',{version!r}), StringStruct('ProductVersion',{version!r}), "
        "StringStruct('ProductName','LeisureLog'), "
        "StringStruct('OriginalFilename','LeisureLog.exe')"
        "])]), VarFileInfo([VarStruct('Translation',[1033,1200])])])",
        encoding="utf-8",
    )
    notices = stage / "third-party"
    notices.mkdir(exist_ok=True)
    names = [
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "alembic",
        "httpx",
        "pydantic-settings",
        "PyYAML",
        "starlette",
        "pydantic",
        "pydantic_core",
        "httpcore",
        "h11",
        "anyio",
        "certifi",
        "idna",
        "click",
        "colorama",
        "Mako",
        "MarkupSafe",
        "typing_extensions",
        "typing-inspection",
        "annotated-types",
        "annotated-doc",
        "python-dotenv",
        "pystray",
        "Pillow",
        "six",
        "PyInstaller",
    ]
    records = []
    for name in names:
        dist = importlib.metadata.distribution(name)
        records.append(
            {
                "name": dist.metadata["Name"],
                "version": dist.version,
                "license": dist.metadata.get("License-Expression", dist.metadata.get("License")),
            }
        )
        for file in dist.files or []:
            if file.name.lower().startswith(("license", "copying", "notice")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = notices / name / file.name
                    target.parent.mkdir(exist_ok=True)
                    shutil.copyfile(source, target)
    python_license = Path(sys.base_prefix) / "LICENSE_PYTHON.txt"
    if python_license.exists():
        shutil.copyfile(python_license, notices / "Python-LICENSE.txt")
    (notices / "dependencies.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return stage


def release_bundle(version):
    folder = ROOT / "dist/LeisureLog"
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    forbidden = {".env", "leisurelog.db", "playnite-library.json", "desktop.json", "runtime.json"}
    if any(path.name in forbidden or "screenshots" in path.parts for path in files):
        raise RuntimeError("Personal data found in bundle; refusing release")
    release = ROOT / "dist/releases"
    release.mkdir(exist_ok=True)
    archive_path = release / f"LeisureLog-{version}-Windows-x64-Standalone.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT / "dist").as_posix())
    manifest = {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    (release / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return release


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iscc", type=Path, help="Path to Inno Setup ISCC.exe")
    parser.add_argument("--skip-bundle", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Build the Windows package on Windows")
    from leisurelog import __version__

    build_resources(__version__)
    if not args.skip_bundle:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--log-level",
                "WARN",
                "--distpath",
                str(ROOT / "dist"),
                "--workpath",
                str(ROOT / "build/pyinstaller"),
                str(ROOT / "packaging/LeisureLog.spec"),
            ],
            cwd=ROOT,
            check=True,
        )
    release = release_bundle(__version__)
    if args.iscc:
        subprocess.run(
            [
                str(args.iscc.resolve()),
                "/DAppVersion=" + __version__,
                str(ROOT / "packaging/LeisureLog.iss"),
            ],
            cwd=ROOT,
            check=True,
        )
    packages = sorted(path for path in release.iterdir() if path.suffix in {".exe", ".zip"})
    (release / "SHA256SUMS.txt").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in packages
        ),
        encoding="utf-8",
    )
    print(json.dumps({"release_directory": str(release), "packages": [str(p) for p in packages]}))


if __name__ == "__main__":
    main()
