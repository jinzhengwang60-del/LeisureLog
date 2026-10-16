"""Compare actual checkpoint/current code and rehearse rollback on synthetic SQLite only.

Run with the project's dependencies installed. Output must be a fresh child of
this checkout's outputs/. No production database, service or Git history is modified.
"""

import argparse
import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "checkpoint/core-plugins-runtime-03"


def scenario(code, data, *, rollback=False, analysis=False):
    from datetime import datetime, timedelta, timezone
    from urllib.parse import quote

    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from leisurelog.config import Settings
    from leisurelog.domain.models import ActivityEvent, IdleEvent, IdleSourceRecord, SourceRecord
    from leisurelog.main import create_app
    from leisurelog.repositories.models import GameSnapshotRow, RawEventRow

    data.mkdir(parents=True, exist_ok=True)
    database_url = "sqlite:///" + (data / "activity.db").as_posix()
    os.environ["LEISURELOG_DATABASE_URL"] = database_url
    if not rollback:
        command.upgrade(Config(str(code / "alembic.ini")), "head")
    rules, export, bindings = (
        data / name for name in ("rules.yaml", "export.json", "bindings.yaml")
    )
    rules.write_text("rules: []\n", encoding="utf-8")
    bindings.write_text(
        'bindings:\n  - name: Synthetic Sandbox\n    app: javaw.exe\n'
        '    title_contains: Minecraft\n', encoding="utf-8",
    )
    settings = Settings(
        database_url=database_url, rules_path=rules, playnite_export_path=export,
        playnite_bindings_path=bindings, plugin_state_path=data / "plugin-state.json",
        auto_sync_enabled=False, auto_backup_days=0,
    )
    start = datetime(2026, 10, 14, 15, 59, 30, tzinfo=timezone.utc)
    window = {"start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat()}
    records = []
    for index, (offset, seconds, app, title) in enumerate([
        (0, 42, "YuanShen.exe", "Synthetic RPG"),
        (60, 30, "YuanShen.exe", "Synthetic RPG"),
        (90, 20, "javaw.exe", "Minecraft 1.21"),
        (120, 15, "javaw.exe", "Other Java program"),
        (150, 30, "YuanShen.exe", "Synthetic RPG"),
    ]):
        event = ActivityEvent(
            f"fixture:{index}", "synthetic", "window", "synthetic-pc",
            start + timedelta(seconds=offset), start + timedelta(seconds=offset + seconds),
            app, title,
        )
        records.append(SourceRecord(
            event, str(index), {"duration": seconds, "app": app, "title": title}, {}
        ))
    for index, (offset, seconds, state) in enumerate([
        (0, 15, "not-afk"), (15, 10, "afk"), (25, 200, "not-afk")
    ]):
        idle = IdleEvent(
            f"idle:{index}", "synthetic", "afk", "synthetic-pc",
            start + timedelta(seconds=offset), start + timedelta(seconds=offset + seconds), state,
        )
        records.append(IdleSourceRecord(idle, str(index), {"status": state}, {}))

    class Source:
        def fetch(self, *args):
            return records

    rpg_id, sandbox_id = ("00000000-0000-4000-8000-00000000000" + str(i) for i in (1, 2))
    rows = [
        {"id": rpg_id, "name": "Synthetic RPG", "installed": True, "directory": "",
         "tags": ["RPG"], "executables": ["YuanShen.exe"], "playtime": 999999999},
        {"id": sandbox_id, "name": "Synthetic Sandbox", "installed": True, "directory": "",
         "tags": ["Sandbox"], "executables": ["javaw.exe"]},
    ]
    payload = {"schema_version": 1, "exported_at": "2026-10-14T00:00:00Z", "games": rows}
    app = create_app(settings, Source())
    captures = {}
    with TestClient(app) as client:
        def capture(label):
            current = {}
            for path in ("/api/events", "/api/sessions", "/api/stats/summary",
                         "/api/game-statistics?scope=all"):
                response = client.get(path)
                response.raise_for_status()
                current[path] = response.json()
            if analysis:
                for path in (
                    "/api/game-types", "/api/game-preferences?start=2026-01-01&end=2026-12-31",
                    "/api/game-statistics?scope=all&sort=recent&limit=1&offset=1",
                ):
                    response = client.get(path)
                    response.raise_for_status()
                    current[path] = response.json()
                for item in current["/api/game-statistics?scope=all"]["items"]:
                    path = "/api/game-statistics/" + quote(item["key"], safe="")
                    response = client.get(path)
                    response.raise_for_status()
                    current[path] = response.json()
            with app.state.sessions() as db:
                current["raw"] = [row.payload for row in
                                  db.scalars(select(RawEventRow).order_by(RawEventRow.id))]
                current["game_snapshots"] = [row.payload for row in
                    db.scalars(select(GameSnapshotRow).order_by(GameSnapshotRow.id))]
            captures[label] = current

        def post(path, body=None):
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()

        if rollback:
            capture("before_reprocess")
            post("/api/reprocess")
            capture("after_reprocess")
            captures["health"] = client.get("/health").json()
            captures["plugin_configuration_error"] = (
                client.get("/api/plugins").json()["configuration_error"]
            )
            return captures

        post("/api/sync/activitywatch", window)
        capture("before_import")
        export.write_text(json.dumps(payload), encoding="utf-8")
        assert post("/api/games/playnite/import")["changed"] is True
        capture("imported")
        if analysis:
            client.put("/api/game-types/playnite:" + rpg_id, json={
                "primary": "card", "tags": ["indie", "独立游戏", "Synthetic manual tag"],
            }).raise_for_status()
            capture("manual_type")
        payload["exported_at"] = "2026-10-15T00:00:00Z"
        export.write_text(json.dumps(payload), encoding="utf-8")
        assert post("/api/games/playnite/import")["changed"] is False
        capture("timestamp_only")
        event_id = client.get("/api/events").json()[0]["id"]
        client.put("/api/events/" + event_id + "/override", json={
            "category": "work", "content": "Manual choice"
        }).raise_for_status()
        capture("manual")
        payload["games"][0]["name"] = "Renamed Synthetic RPG"
        export.write_text(json.dumps(payload), encoding="utf-8")
        post("/api/games/playnite/import")
        capture("renamed")
        export.write_text("broken", encoding="utf-8")
        assert client.post("/api/games/playnite/import").status_code == 422
        post("/api/reprocess")
        capture("damaged_export")
        export.write_text(json.dumps(payload), encoding="utf-8")
        client.delete("/api/events/" + event_id + "/override").raise_for_status()
        capture("manual_removed")
        if analysis:
            client.delete("/api/game-types/playnite:" + rpg_id).raise_for_status()
            capture("manual_type_reset")
        payload["games"] = []
        export.write_text(json.dumps(payload), encoding="utf-8")
        post("/api/games/playnite/import")
        capture("empty_catalog")
        payload["games"] = rows
        export.write_text(json.dumps(payload), encoding="utf-8")
        post("/api/games/playnite/import")
        post("/api/classification/reload-rules")
        post("/api/reprocess")
        capture("restored")
        if analysis:
            client.put("/api/game-types/playnite:" + rpg_id, json={
                "primary": "strategy", "tags": ["Synthetic rollback tag"],
            }).raise_for_status()
            capture("restored_with_manual_type")
        if hasattr(app.state, "plugins") and any(
            p["id"] == "leisurelog.playnite" for p in app.state.plugins.snapshot()["plugins"]
        ):
            from leisurelog.game_integration import PLAYNITE_ID, PLAYNITE_PERMISSIONS

            app.state.plugins.disable(PLAYNITE_ID)
            app.state.plugins.enable(PLAYNITE_ID, {PLAYNITE_ID: PLAYNITE_PERMISSIONS})
    return captures


def _child(code, data, output, *, rollback=False, analysis=False):
    env = {**os.environ, "PYTHONPATH": str(code / "src"), "PYTHONUTF8": "1"}
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--child-code", str(code),
               "--child-data", str(data), "--child-output", str(output)]
    if rollback:
        command.append("--rollback")
    if analysis:
        command.append("--analysis")
    result = subprocess.run(command, cwd=code, env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=120)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return json.loads(output.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "outputs/game-catalog-validation/parity"
    )
    parser.add_argument("--child-code", type=Path)
    parser.add_argument("--child-data", type=Path)
    parser.add_argument("--child-output", type=Path)
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--analysis", action="store_true")
    parser.add_argument("--baseline", default=BASELINE)
    args = parser.parse_args()
    if args.child_code:
        allowed = (ROOT / "outputs").resolve()
        if (
            args.child_data is None or args.child_output is None
            or not args.child_data.resolve().is_relative_to(allowed)
            or not args.child_output.resolve().is_relative_to(allowed)
            or (
                args.child_code.resolve() != ROOT
                and not args.child_code.resolve().is_relative_to(allowed)
            )
        ):
            parser.error(
                "Child verification must use code/test data inside this validation workspace"
            )
        value = scenario(args.child_code, args.child_data, rollback=args.rollback,
                         analysis=args.analysis)
        args.child_output.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "outputs").resolve()) or output.exists():
        parser.error("Output must be a fresh directory under this checkout's outputs/")
    output.mkdir(parents=True)
    baseline = output / "baseline-code"
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", args.baseline, "src", "migrations", "alembic.ini"],
        cwd=ROOT, text=True, encoding="utf-8",
    ).splitlines()
    names = [name for name in names if name.endswith(
        (".py", ".html", ".js", ".css", ".svg", ".png", ".woff2")
    ) or name == "alembic.ini"]
    archive = subprocess.check_output(
        ["git", "archive", "--format=zip", args.baseline, "--", *names], cwd=ROOT
    )
    with ZipFile(io.BytesIO(archive)) as zipped:
        for entry in zipped.infolist():
            if not (baseline / entry.filename).resolve().is_relative_to(baseline.resolve()):
                raise ValueError("Baseline archive path escaped the validation directory")
        zipped.extractall(baseline)
    (baseline / "src/leisurelog/api/static").mkdir(parents=True, exist_ok=True)
    before = _child(
        baseline, output / "before-data", output / "before.json", analysis=args.analysis,
    )
    after = _child(ROOT, output / "after-data", output / "after.json", analysis=args.analysis)
    if before != after:
        mismatches = [phase for phase in before if before[phase] != after.get(phase)]
        raise AssertionError("Migration differs from actual checkpoint code: " + str(mismatches))
    rollback_data = output / "rollback-data"
    rollback_data.mkdir()
    with sqlite3.connect(
        "file:" + (output / "after-data/activity.db").as_posix() + "?mode=ro", uri=True
    ) as current, sqlite3.connect(rollback_data / "activity.db") as copy:
        current.backup(copy)
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not copy.execute("PRAGMA foreign_key_check").fetchall()
    (rollback_data / "plugin-state.json").write_bytes(
        (output / ("before-data" if args.analysis else "after-data") /
         "plugin-state.json").read_bytes()
    )
    restored = _child(baseline, rollback_data, output / "rollback.json", rollback=True,
                      analysis=args.analysis)
    assert restored["health"]["database_revision"] == "0013"
    final = "restored_with_manual_type" if args.analysis else "restored"
    assert restored["before_reprocess"] == after[final]
    assert restored["after_reprocess"] == after[final]
    report = {
        "baseline": args.baseline, "phases_equal": list(before), "schema": "0013",
        "rollback_reads_and_reprocesses_current_synthetic_database": True,
        "matching_rollback_configuration": args.analysis,
        "rollback_configuration_error": restored["plugin_configuration_error"],
        "scope": "synthetic inputs only; no production database or service accessed",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
