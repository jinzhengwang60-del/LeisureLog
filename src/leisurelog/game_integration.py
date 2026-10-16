"""Fixed official game assembly and host transactions, outside the activity use case.

This is the sole composition point for the game catalog repository and fixed
Playnite package. Nothing here is passed to plugin code as a context/provider.
"""

from dataclasses import dataclass, field
from importlib import import_module
from uuid import UUID

from sqlalchemy import text

from leisurelog.domain.classification import ClassificationPipeline
from leisurelog.domain.game_catalog import GameCatalogUnavailable
from leisurelog.domain.plugin_runtime import PluginConfiguration, PluginDefinition
from leisurelog.domain.plugins import PLUGIN_API_VERSION, PluginCapability, PluginManifest
from leisurelog.domain.plugins import PluginPermission as Permission
from leisurelog.repositories.games import SQLiteGameCatalog
from leisurelog.repositories.sqlite import SQLiteRepository
from leisurelog.services.games import GameImportService
from leisurelog.services.processing import ProcessingService

PLAYNITE_ID = "leisurelog.playnite"
PLAYNITE_PERMISSIONS = (
    Permission.FILE_IMPORT,
    Permission.GAME_CATALOG_PROPOSE,
    Permission.GAME_CATALOG_READ,
    Permission.DETAILS_READ,
    Permission.CLASSIFICATION_PROPOSE,
)


def official_game_definition():
    manifest = PluginManifest(
        PLAYNITE_ID,
        "Playnite 游戏资料与识别",
        "0.1.0",
        ">=0.4.0b1,<0.6",
        PLUGIN_API_VERSION,
        (PluginCapability.GAME_CATALOG, PluginCapability.CLASSIFIER),
        PLAYNITE_PERMISSIONS,
    )
    # A fixed reviewed package; neither HTTP nor saved configuration chooses a module.
    return PluginDefinition(
        manifest,
        lambda context: import_module("leisurelog_plugins.playnite").create(context),
        required_permissions=(Permission.GAME_CATALOG_READ,),
    )


def official_game_defaults():
    # Compatibility for the formerly built-in feature, only when no saved choice exists.
    return PluginConfiguration(enabled={PLAYNITE_ID: PLAYNITE_PERMISSIONS})


def validate_playnite_import(proposal):
    """Compatibility of this fixed source slot, not a rule in the unified DTO."""
    try:
        payload = proposal.payload()
        if (
            type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1
            or type(payload.get("games")) is not list
            or len(payload["games"]) != len(proposal.games)
            or {str(UUID(row["id"])) for row in payload["games"]} != {g.id for g in proposal.games}
        ):
            raise ValueError("Source snapshot and normalized identities disagree")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise GameCatalogUnavailable("Playnite 原始快照与处理后的资料不一致") from error


@dataclass(frozen=True)
class _EmptyCovers:
    covers: dict = field(default_factory=dict)

    def cover_for(self, name, apps=()):
        return None


class _MissingMedia:
    def covers(self):
        return _EmptyCovers()


class _GameMedia:
    def __init__(self, runtime, media):
        self._runtime, self._media = runtime, media

    def covers(self):
        try:
            return self._runtime.read_game_media(PLAYNITE_ID, self._media.covers)
        except Exception:
            return _EmptyCovers()


def game_media(settings, runtime):
    """Existing covers remain a presentation feature pending the page/media batch."""
    try:
        media = import_module("leisurelog_plugins.playnite").PlayniteAdapter(
            settings.playnite_export_path, settings.playnite_bindings_path
        )
    except Exception:
        media = _MissingMedia()
    return _GameMedia(runtime, media)


class StoredGameCatalog:
    def __init__(self, sessions):
        self._sessions = sessions

    def read(self):
        with self._sessions() as db:
            db.execute(text("BEGIN"))
            return SQLiteGameCatalog(db).snapshot()


class GameCatalogHost:
    def __init__(self, sessions, runtime, pipeline, settings):
        self._sessions, self._runtime, self._pipeline = sessions, runtime, pipeline
        self._settings = settings

    def status(self):
        with self._sessions() as db:
            db.execute(text("BEGIN"))
            return {
                "export_path": str(self._settings.playnite_export_path.resolve()),
                **SQLiteGameCatalog(db).status(),
            }

    def refresh(self):
        # Plugin code/files run before taking the shared SQLite writer lock.
        ticket = self._runtime.fetch_game_catalog(PLAYNITE_ID)
        validate_playnite_import(ticket.proposal)
        with self._sessions() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            catalog = SQLiteGameCatalog(db)
            processor = None

            def processing():
                nonlocal processor
                pipeline = self._pipeline()
                bound = self._runtime.for_processing(catalog.snapshot())
                pipeline = ClassificationPipeline(
                    [bound if value is self._runtime else value for value in pipeline.classifiers],
                    pipeline.timing_rules,
                    pipeline.context_classifiers,
                )
                processor = ProcessingService(
                    SQLiteRepository(db), pipeline, self._settings.session_gap_seconds
                )
                return processor

            try:
                result = GameImportService(catalog, processing).import_catalog(ticket.proposal)
                # Revoke/disable and this final commit have one defined ordering.
                self._runtime.commit_game_catalog(ticket, db.commit)
            except Exception:
                db.rollback()
                raise
            if processor is not None:
                result["processing"] = processor.last_work
            return result
