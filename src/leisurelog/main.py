from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import make_url

from leisurelog import __version__
from leisurelog.adapters.activitywatch import ActivityWatchAdapter
from leisurelog.adapters.catalog_files import LocalGameCatalogFiles
from leisurelog.adapters.plugin_pages import PluginPageHost, PluginResources
from leisurelog.adapters.plugin_workers import ThreadPluginWorkers
from leisurelog.adapters.rules import RuleClassifier
from leisurelog.adapters.scheduler import PeriodicSync
from leisurelog.analysis_integration import (
    official_analysis_definition,
    official_defaults,
    official_extension_bindings,
)
from leisurelog.api.activity_context import router as activity_context_router
from leisurelog.api.dashboard import router as dashboard_router
from leisurelog.api.game_catalog import router as game_catalog_router
from leisurelog.api.library import router as library_router
from leisurelog.api.plugin_features import install_feature_routes
from leisurelog.api.plugin_features import router as plugin_features_router
from leisurelog.api.plugin_management import router as plugin_management_router
from leisurelog.api.plugins import router as plugins_router
from leisurelog.api.review import router as review_router
from leisurelog.api.routes import router
from leisurelog.api.rules_reload import router as rules_reload_router
from leisurelog.api.statistics import router as statistics_router
from leisurelog.api.storage import router as storage_router
from leisurelog.api.unclassified import router as unclassified_router
from leisurelog.config import Settings
from leisurelog.domain.classification import ClassificationPipeline
from leisurelog.game_integration import (
    PLAYNITE_ID,
    GameCatalogHost,
    StoredGameCatalog,
    game_media,
    official_game_definition,
)
from leisurelog.repositories.database import make_engine, session_factory
from leisurelog.repositories.plugin_state import FilePluginState
from leisurelog.repositories.plugin_summary import SQLitePluginSummary
from leisurelog.repositories.storage import SQLiteStorage
from leisurelog.runtime import AutomaticSync
from leisurelog.services.plugin_extensions import ExtensionExecutors
from leisurelog.services.plugin_runtime import PluginRuntime
from leisurelog.services.storage import AutomaticBackup, StorageService


def create_app(
    settings: Settings | None = None,
    source=None,
    *,
    plugins=None,
    extensions=None,
) -> FastAPI:
    settings = settings or Settings()
    bindings = extensions if extensions is not None else official_extension_bindings()

    @asynccontextmanager
    async def lifespan(app):
        rules = RuleClassifier(settings.rules_path)
        engine = make_engine(settings.database_url)
        app.state.settings = settings
        app.state.sessions = session_factory(engine)
        state_path = settings.plugin_state_path or (
            Path(make_url(settings.database_url).database).parent / "plugin-state.json"
        )
        official = plugins is None
        page_resources = PluginResources(bindings.resources)
        plugin_state = FilePluginState(
            state_path, defaults=official_defaults() if official else None
        )
        plugin_runtime = PluginRuntime(
            (official_game_definition(), official_analysis_definition())
            if official
            else tuple(plugins),
            ThreadPluginWorkers(),
            plugin_state,
            SQLitePluginSummary(app.state.sessions),
            app_version=__version__,
            catalog_reader=StoredGameCatalog(app.state.sessions),
            catalog_files={
                PLAYNITE_ID: LocalGameCatalogFiles(
                    settings.playnite_export_path, settings.playnite_bindings_path
                )
            },
            page_validator=page_resources.validate,
        )
        app.state.plugins = plugin_runtime
        app.state.extensions = ExtensionExecutors(
            {
                owner: factory(app.state.sessions, plugin_runtime)
                for owner, factory in bindings.hosts.items()
            }
        )
        app.state.plugin_pages = PluginPageHost(
            plugin_runtime.extensions,
            page_resources,
            bindings.pages,
        )
        pipeline = ClassificationPipeline([rules, plugin_runtime], rules.timing_rules, [rules])
        app.state.pipeline = pipeline
        app.state.game_catalog = GameCatalogHost(
            app.state.sessions, plugin_runtime, lambda: app.state.pipeline, settings
        )
        app.state.playnite = game_media(settings, plugin_runtime)
        app.state.storage = StorageService(
            SQLiteStorage(
                Path(make_url(settings.database_url).database),
                settings.rules_path,
                settings.backup_dir,
                supplemental_files=lambda: {
                    "config/plugin-state.json": plugin_state.backup_snapshot(),
                },
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
                        app.state.game_catalog.refresh,
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
                plugin_runtime.start()
                scheduler.start()
                backup_scheduler.start()
                try:
                    yield
                finally:
                    scheduler.stop()
                    backup_scheduler.stop()
        finally:
            # Timed-out plugin reads may still own SQLite connections. Dispose only
            # after their callable bodies have exited; future access is already revoked.
            plugin_runtime.close()
            plugin_runtime.when_drained(engine.dispose)

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
    app.include_router(plugins_router)
    app.include_router(plugin_management_router)
    app.include_router(game_catalog_router)
    app.include_router(plugin_features_router)
    app.include_router(unclassified_router)
    app.include_router(rules_reload_router)
    app.include_router(review_router)
    app.include_router(activity_context_router)
    app.mount(
        "/static", StaticFiles(directory=Path(__file__).parent / "api" / "static"), name="static"
    )
    install_feature_routes(app, bindings.endpoints, bindings.pages)
    return app
