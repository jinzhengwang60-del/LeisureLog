from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import make_url

from leisurelog import __version__
from leisurelog.adapters.activitywatch import ActivityWatchAdapter
from leisurelog.adapters.playnite import PlayniteAdapter
from leisurelog.adapters.rules import RuleClassifier
from leisurelog.adapters.scheduler import PeriodicSync
from leisurelog.api.activity_context import router as activity_context_router
from leisurelog.api.dashboard import router as dashboard_router
from leisurelog.api.game_preferences import router as game_preferences_router
from leisurelog.api.games import router as games_router
from leisurelog.api.library import router as library_router
from leisurelog.api.review import router as review_router
from leisurelog.api.routes import router
from leisurelog.api.rules_reload import router as rules_reload_router
from leisurelog.api.statistics import router as statistics_router
from leisurelog.api.storage import router as storage_router
from leisurelog.api.unclassified import router as unclassified_router
from leisurelog.config import Settings
from leisurelog.domain.classification import ClassificationPipeline
from leisurelog.repositories.database import make_engine, session_factory
from leisurelog.repositories.storage import SQLiteStorage
from leisurelog.runtime import AutomaticSync
from leisurelog.services.storage import AutomaticBackup, StorageService


def create_app(settings: Settings | None = None, source=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        rules = RuleClassifier(settings.rules_path)
        pipeline = ClassificationPipeline([rules], rules.timing_rules, [rules])
        engine = make_engine(settings.database_url)
        app.state.settings = settings
        app.state.sessions = session_factory(engine)
        app.state.pipeline = pipeline
        app.state.playnite = PlayniteAdapter(
            settings.playnite_export_path, settings.playnite_bindings_path
        )
        app.state.storage = StorageService(
            SQLiteStorage(
                Path(make_url(settings.database_url).database),
                settings.rules_path,
                settings.backup_dir,
            )
        )
        try:
            with httpx.Client(
                base_url=settings.activitywatch_url, timeout=20, trust_env=False
            ) as client:
                app.state.source = (
                    source
                    if source is not None
                    else ActivityWatchAdapter(client, settings.browser_device_bindings)
                )
                scheduler = PeriodicSync(
                    AutomaticSync(
                        app.state.sessions,
                        app.state.source,
                        pipeline,
                        settings,
                        app.state.playnite,
                    ),
                    settings.auto_sync_interval_seconds,
                    settings.auto_sync_enabled,
                )
                app.state.scheduler = scheduler
                backup_scheduler = PeriodicSync(
                    AutomaticBackup(
                        app.state.storage, settings.auto_backup_days, settings.auto_backup_keep
                    ),
                    settings.auto_backup_check_seconds,
                    settings.auto_backup_days > 0,
                    task="backup",
                )
                app.state.backup_scheduler = backup_scheduler
                scheduler.start()
                backup_scheduler.start()
                try:
                    yield
                finally:
                    scheduler.stop()
                    backup_scheduler.stop()
        finally:
            engine.dispose()

    app = FastAPI(title="LeisureLog · 电脑活动记录", version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def current_activity_data(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/") or request.url.path == "/health":
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(router)
    app.include_router(dashboard_router)
    app.include_router(storage_router)
    app.include_router(statistics_router)
    app.include_router(library_router)
    app.include_router(games_router)
    app.include_router(game_preferences_router)
    app.include_router(unclassified_router)
    app.include_router(rules_reload_router)
    app.include_router(review_router)
    app.include_router(activity_context_router)
    app.mount(
        "/static", StaticFiles(directory=Path(__file__).parent / "api" / "static"), name="static"
    )
    return app
