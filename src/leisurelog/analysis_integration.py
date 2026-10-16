"""Official analysis assembly and host-owned projection/type transactions."""

from importlib import import_module
from pathlib import Path

from sqlalchemy import text

from leisurelog.adapters.game_queries import (
    EmptyQuery,
    GameDetailQuery,
    GameListQuery,
    GameRangeQuery,
    GameTypeChoice,
)
from leisurelog.domain.game_types import validate_choice
from leisurelog.domain.plugin_extensions import (
    AnalysisRequest,
    ExtensionEndpoint,
    ExtensionPageRoute,
    HostExtensionBindings,
    JsonSnapshot,
)
from leisurelog.domain.plugin_runtime import PluginConfiguration, PluginDefinition
from leisurelog.domain.plugins import PLUGIN_API_VERSION, PluginCapability, PluginManifest
from leisurelog.domain.plugins import PluginPermission as Permission
from leisurelog.game_integration import official_game_defaults
from leisurelog.repositories.game_views import SQLiteGameViews

ANALYSIS_ID = "leisurelog.game-analysis"
ANALYSIS_PERMISSIONS = (
    Permission.SUMMARY_READ,
    Permission.GAME_STATISTICS_READ,
    Permission.DETAILS_READ,
    Permission.GAME_TYPES_WRITE,
)


def official_analysis_definition():
    return PluginDefinition(
        PluginManifest(
            ANALYSIS_ID,
            "游戏统计、类型与偏好",
            "0.1.0",
            ">=0.4.0b1,<0.6",
            PLUGIN_API_VERSION,
            (PluginCapability.ANALYTICS, PluginCapability.PAGE),
            ANALYSIS_PERMISSIONS,
        ),
        lambda context: import_module("leisurelog_plugins.game_analysis").create(context),
        required_permissions=(Permission.GAME_STATISTICS_READ,),
    )


def official_defaults():
    return PluginConfiguration(
        enabled={
            **official_game_defaults().enabled,
            ANALYSIS_ID: ANALYSIS_PERMISSIONS,
        }
    )


def analysis_endpoints():
    return (
        ExtensionEndpoint(ANALYSIS_ID, "listing", "GET", "/api/game-statistics", GameListQuery),
        ExtensionEndpoint(
            ANALYSIS_ID, "detail", "GET", "/api/game-statistics/{key:path}", GameDetailQuery
        ),
        ExtensionEndpoint(
            ANALYSIS_ID, "preferences", "GET", "/api/game-preferences", GameRangeQuery
        ),
        ExtensionEndpoint(ANALYSIS_ID, "options", "GET", "/api/game-types", EmptyQuery),
        ExtensionEndpoint(
            ANALYSIS_ID, "save", "PUT", "/api/game-types/{key:path}", EmptyQuery, GameTypeChoice
        ),
        ExtensionEndpoint(ANALYSIS_ID, "reset", "DELETE", "/api/game-types/{key:path}", EmptyQuery),
    )


def analysis_pages():
    return (
        ExtensionPageRoute(ANALYSIS_ID, "games", "/games"),
        ExtensionPageRoute(ANALYSIS_ID, "preferences", "/game-preferences"),
    )


def analysis_resources():
    # A fixed package root works in a source checkout, wheel and PyInstaller bundle.
    return {ANALYSIS_ID: Path(__file__).parent.parent / "leisurelog_plugins/game_analysis/static"}


def official_extension_bindings():
    return HostExtensionBindings(
        endpoints=analysis_endpoints(),
        pages=analysis_pages(),
        resources=analysis_resources(),
        hosts={ANALYSIS_ID: GameAnalysisHost},
    )


class GameAnalysisHost:
    def __init__(self, sessions, runtime):
        self._sessions, self._extensions = sessions, runtime.extensions

    def execute(self, endpoint, parameters):
        if endpoint.owner != ANALYSIS_ID:
            raise KeyError("宿主没有登记这个数据投影")
        if "key" in parameters and (
            type(parameters["key"]) is not str
            or not parameters["key"]
            or len(parameters["key"]) > 4096
        ):
            raise ValueError("游戏条目标识过长或无效")
        # The data provider enforces its own minimum grants. A plugin cannot
        # obtain details by understating permissions in its contribution.
        required = {
            "listing": (Permission.GAME_STATISTICS_READ,),
            "preferences": (Permission.GAME_STATISTICS_READ,),
            "detail": (Permission.GAME_STATISTICS_READ, Permission.DETAILS_READ),
            "options": (Permission.SUMMARY_READ,),
            "save": (
                Permission.GAME_STATISTICS_READ,
                Permission.DETAILS_READ,
                Permission.GAME_TYPES_WRITE,
            ),
            "reset": (
                Permission.GAME_STATISTICS_READ,
                Permission.DETAILS_READ,
                Permission.GAME_TYPES_WRITE,
            ),
        }[endpoint.name]
        ticket = self._extensions.begin(endpoint.owner, endpoint.name, permissions=required)
        parameter_snapshot = JsonSnapshot.from_value(parameters)
        write = endpoint.method in {"PUT", "DELETE"}
        with self._sessions() as db:
            db.execute(text("BEGIN IMMEDIATE" if write else "BEGIN"))
            views = SQLiteGameViews(db)
            try:
                view = "options" if write else endpoint.name
                result = self._extensions.invoke(
                    ticket,
                    endpoint.name,
                    AnalysisRequest(
                        parameter_snapshot,
                        views.read(view, parameters),
                    ),
                )
                if write:
                    change = result.change
                    if (
                        change is None
                        or change.key != parameters["key"]
                        or ((change.primary is None) != (endpoint.name == "reset"))
                    ):
                        self._extensions.reject(ticket)
                    if not views.store.exists(change.key):
                        raise KeyError(change.key)
                    if change.primary is None:
                        views.store.remove_type(change.key)
                    else:
                        # Validate again in the host, independent of the plugin suggestion.
                        tags = validate_choice(change.primary, list(change.tags))
                        views.store.save_type(change.key, change.primary, tags)
                    result = self._extensions.invoke(
                        ticket,
                        "detail",
                        AnalysisRequest(
                            parameter_snapshot,
                            views.read("detail", parameters),
                        ),
                    )
                    if result.change is not None:
                        self._extensions.reject(ticket)
                    # Serialize the final commit with disable/revoke and generation changes.
                    self._extensions.commit(ticket, db.commit)
                else:
                    if result.change is not None:
                        self._extensions.reject(ticket)
                    db.commit()
                return result.data.value()
            except BaseException:
                db.rollback()
                raise
