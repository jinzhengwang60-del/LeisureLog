"""Public plugin surface. Keep explicit exports; never expose an app or repository."""

from leisurelog.domain.game_catalog import (
    GameCatalogClassifier,
    GameCatalogFiles,
    GameCatalogFilesReader,
    GameCatalogImport,
    GameCatalogSnapshot,
    GameCatalogSource,
    GameCatalogUnavailable,
    GameMatch,
)
from leisurelog.domain.game_types import (
    canonical_tags,
    resolve_game_type,
    type_options,
    validate_choice,
)
from leisurelog.domain.games import Game
from leisurelog.domain.models import ActivityEvent, Classification
from leisurelog.domain.plugin_contracts import (
    ActivitySummary,
    CategoryTotal,
    PluginTask,
    SummaryQuery,
    SummaryReader,
    TaskBudget,
    TaskContext,
    TaskHandle,
    TaskStopResult,
    ThemeContribution,
)
from leisurelog.domain.plugin_extensions import (
    AnalysisRejected,
    AnalysisRequest,
    AnalysisResult,
    AnalyticsContribution,
    Analyzer,
    GameTypeChange,
    JsonSnapshot,
    PageContribution,
)
from leisurelog.domain.plugin_runtime import (
    PluginContext,
    PluginContributions,
    ScheduledTask,
)
from leisurelog.domain.plugins import PLUGIN_API_VERSION, PluginCapability, PluginPermission
from leisurelog.domain.ports import Classifier

__all__ = (
    "PLUGIN_API_VERSION",
    "ActivityEvent",
    "ActivitySummary",
    "AnalysisRejected",
    "AnalysisRequest",
    "AnalysisResult",
    "AnalyticsContribution",
    "Analyzer",
    "CategoryTotal",
    "Classification",
    "Classifier",
    "Game",
    "GameCatalogClassifier",
    "GameCatalogFiles",
    "GameCatalogFilesReader",
    "GameCatalogImport",
    "GameCatalogSnapshot",
    "GameCatalogSource",
    "GameCatalogUnavailable",
    "GameMatch",
    "GameTypeChange",
    "JsonSnapshot",
    "PageContribution",
    "PluginCapability",
    "PluginContext",
    "PluginContributions",
    "PluginPermission",
    "PluginTask",
    "ScheduledTask",
    "SummaryQuery",
    "SummaryReader",
    "TaskBudget",
    "TaskContext",
    "TaskHandle",
    "TaskStopResult",
    "ThemeContribution",
    "canonical_tags",
    "resolve_game_type",
    "type_options",
    "validate_choice",
)
