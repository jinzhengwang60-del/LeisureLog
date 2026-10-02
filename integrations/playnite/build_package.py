"""Produce the local Playnite extension package with an explicit export destination."""

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def build(export_path: Path, output: Path):
    root = Path(__file__).resolve().parent
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.write(root / "extension.yaml", "extension.yaml")
        # Windows PowerShell 5.1 requires the BOM for non-ASCII script text.
        archive.writestr("LeisureLog.psm1", (root / "LeisureLog.psm1").read_text(
            encoding="utf-8-sig"
        ).encode("utf-8-sig"))
        archive.writestr("settings.json", json.dumps(
            {"export_path": str(export_path.resolve())}, ensure_ascii=False
        ))
    return output


if __name__ == "__main__":
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-path", type=Path, default=project / "data/playnite-library.json")
    parser.add_argument("--output", type=Path, default=project / "dist/LeisureLog-Playnite.pext")
    args = parser.parse_args()
    print(build(args.export_path, args.output))
