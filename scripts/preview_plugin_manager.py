"""Run an explicitly marked plugin management preview on new synthetic data only."""

import argparse
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import uvicorn
from alembic import command
from alembic.config import Config
from fastapi.responses import Response
from sqlalchemy import text

from leisurelog.analysis_integration import official_analysis_definition, official_defaults
from leisurelog.config import Settings
from leisurelog.domain.models import ActivityEvent, SourceRecord
from leisurelog.domain.plugin_contracts import TaskBudget
from leisurelog.domain.plugin_runtime import PluginContributions, PluginDefinition, ScheduledTask
from leisurelog.domain.plugins import PluginCapability, PluginManifest
from leisurelog.game_integration import official_game_definition
from leisurelog.main import create_app
from leisurelog.repositories.plugin_state import FilePluginState
from leisurelog.repositories.sqlite import SQLiteRepository
from leisurelog.services.processing import ProcessingService

ROOT = Path(__file__).resolve().parents[1]


def application(data, demos=False):
    data = data.resolve()
    if not data.is_relative_to((ROOT / "outputs").resolve()) or data.exists():
        raise ValueError("Preview data must be a new child of this checkout's outputs/")
    data.mkdir(parents=True)
    url = "sqlite:///" + (data / "activity.db").as_posix()
    migration = Config(str(ROOT / "alembic.ini"))
    migration.attributes["database_url"] = url
    command.upgrade(migration, "head")
    rules, bindings, export = (
        data / name for name in ("rules.yaml", "bindings.yaml", "export.json")
    )
    rules.write_text("rules: []\n", encoding="utf-8")
    bindings.write_text("bindings: []\n", encoding="utf-8")
    export.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "exported_at": "2026-10-15T00:00:00Z",
                "games": [
                    {
                        "id": "11111111-1111-4111-8111-111111111111",
                        "name": "隔离示例游戏",
                        "installed": True,
                        "directory": "",
                        "tags": ["ARPG"],
                        "executables": ["sample-game.exe"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    state_path = data / "plugin-state.json"
    defaults = official_defaults()
    FilePluginState(state_path).save(type(defaults)(1, defaults.enabled), expected_revision=0)
    definitions = [official_game_definition(), official_analysis_definition()]
    release = Event()
    if demos:

        def failed(context):
            raise RuntimeError("synthetic private exception must remain hidden")

        definitions.append(
            PluginDefinition(
                PluginManifest(
                    "example.failed",
                    "演示：启动失败",
                    "0.1.0",
                    ">=0.4.0b1,<0.6",
                    1,
                ),
                failed,
            )
        )
        definitions.append(
            PluginDefinition(
                PluginManifest(
                    "example.waiting",
                    "演示：任务等待退出",
                    "0.1.0",
                    ">=0.4.0b1,<0.6",
                    1,
                    (PluginCapability.TASK,),
                ),
                lambda context: PluginContributions(
                    tasks=(
                        ScheduledTask(
                            "held",
                            SimpleNamespace(run=lambda context: release.wait(240)),
                            budget=TaskBudget(300, 0.1),
                        ),
                    )
                ),
            )
        )
    settings = Settings(
        database_url=url,
        rules_path=rules,
        plugin_state_path=state_path,
        playnite_export_path=export,
        playnite_bindings_path=bindings,
        auto_sync_enabled=False,
        auto_backup_days=0,
    )
    app = create_app(settings, SimpleNamespace(fetch=lambda *args: []), plugins=tuple(definitions))
    lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def fixture_lifespan(app):
        async with lifespan(app):
            app.state.game_catalog.refresh()
            start = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
            event = ActivityEvent(
                "preview:1",
                "synthetic",
                "window",
                "preview-pc",
                start,
                start + timedelta(seconds=120),
                "sample-game.exe",
                "隔离示例游戏",
            )
            with app.state.sessions() as db:
                db.execute(text("BEGIN IMMEDIATE"))
                repository = SQLiteRepository(db)
                repository.ingest(
                    SourceRecord(
                        event,
                        "1",
                        {"app": event.app, "title": event.title},
                        {},
                    )
                )
                ProcessingService(
                    repository,
                    app.state.pipeline,
                    settings.session_gap_seconds,
                ).rebuild_changed()
                db.commit()
            try:
                yield
            finally:
                release.set()

    app.router.lifespan_context = fixture_lifespan

    @app.middleware("http")
    async def mark_preview(request, call_next):
        response = await call_next(request)
        if (
            request.url.path in {"/plugins", "/games", "/game-preferences"}
            and response.status_code == 200
        ):
            content = b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")
            marker = '<p class="notice">隔离测试页面 · 全部记录为合成数据 · 不连接日常数据库</p>'
            headers = {
                key: value for key, value in response.headers.items() if key != "content-length"
            }
            response = Response(
                content.replace("<main>", "<main>" + marker),
                headers=headers,
                media_type="text/html",
            )
        response.headers["X-LeisureLog-Test-Fixture"] = "synthetic"
        return response

    if demos:

        @app.post("/api/demo/release", include_in_schema=False)
        def release_fixture():
            release.set()
            return {"released": True}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8736)
    parser.add_argument("--demos", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    uvicorn.run(application(args.data_dir, args.demos), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
