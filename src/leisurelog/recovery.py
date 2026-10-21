"""Offline, non-overwriting recovery of a verified full backup into a new directory."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from leisurelog import DATABASE_REVISION
from leisurelog.adapters.rules import RuleClassifier
from leisurelog.repositories.storage import file_sha256, validate_manifest, verify_restore

_FILES = {
    "leisurelog.db": "data/leisurelog.db",
    "config/rules.yaml": "config/rules.yaml",
    "config/plugin-state.json": "data/plugin-state.json",
    "verification.json": "verification.json",
}


def recover_archive(archive: Path, destination: Path) -> dict:
    """Verify every file before publishing the new directory; never touch the live store."""
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Recovery destination must be a new directory")
    if not destination.parent.is_dir():
        raise ValueError("Recovery destination parent does not exist")
    with TemporaryDirectory(prefix=".leisurelog-recovery-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "recovered"
        staged.mkdir()
        with ZipFile(archive) as bundle:
            entries = bundle.infolist()
            names = {item.filename for item in entries}
            if (
                len(entries) != len(names)
                or not {"leisurelog.db", "config/rules.yaml", "verification.json"} <= names
                or not names <= _FILES.keys()
            ):
                raise ValueError("Unexpected, missing or duplicate recovery files")
            for item in entries:
                limit = 64 * 1024**3 if item.filename == "leisurelog.db" else 1024**2
                if item.file_size > limit or item.is_dir():
                    raise ValueError("Recovery file exceeds size limit")
                target = staged / _FILES[item.filename]
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        manifest = validate_manifest(json.loads(
            (staged / "verification.json").read_text(encoding="utf-8")
        ))
        actual = verify_restore(staged / "data/leisurelog.db")
        if actual != manifest["verification"]:
            raise ValueError("Recovered database differs from backup verification")
        if actual["database_revision"] != DATABASE_REVISION:
            raise ValueError("Use a compatible application version to migrate this backup first")
        for name, digest in manifest.get("files", {}).items():
            if name not in names or name == "verification.json":
                raise ValueError("Invalid recovery checksum entry")
            if file_sha256(staged / _FILES[name]) != digest:
                raise ValueError("Recovery file checksum differs from backup")
        for name, entry in manifest.get("supplemental_files", {}).items():
            if name not in names or name != "config/plugin-state.json":
                raise ValueError("Missing supplemental recovery file")
            content = (staged / _FILES[name]).read_bytes()
            if (
                len(content) != entry["bytes"]
                or hashlib.sha256(content).hexdigest() != entry["sha256"]
            ):
                raise ValueError("Supplemental recovery file checksum differs from backup")
        RuleClassifier(staged / "config/rules.yaml")
        # Windows rename refuses an existing destination, including an empty directory.
        # Recheck for platforms whose rename permits replacing an empty directory.
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Recovery destination already exists")
        staged.rename(destination)
    return {
        "destination": str(destination),
        "database_revision": actual["database_revision"],
        "tables": actual["tables"],
        "plugin_state_restored": "config/plugin-state.json" in names,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验完整备份并恢复到新的目录，不覆盖现有数据。")
    parser.add_argument("archive", type=Path, help="从存储与备份下载的完整 ZIP")
    parser.add_argument("--destination", type=Path, required=True, help="尚不存在的目标目录")
    args = parser.parse_args(argv)
    try:
        result = recover_archive(args.archive, args.destination)
    except Exception as exc:
        print(f"恢复未完成：{exc}", file=sys.stderr)
        return 2
    print(f'恢复校验通过：{result["destination"]}')
    print("当前运行的数据未替换。请按维护说明在确认后切换；保留源备份。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
