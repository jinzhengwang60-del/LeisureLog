"""Verify host calls, permission denial, provenance and existing manual priority."""

from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from leisurelog import plugin_api
from leisurelog.domain.classification import ClassificationPipeline
from leisurelog.domain.models import ActivityEvent as CoreEvent
from leisurelog.domain.plugins import PluginManifest
from leisurelog.plugin_api import (
    ActivityEvent,
    ActivitySummary,
    CategoryTotal,
    Classification,
    PluginCapability,
    PluginPermission,
    SummaryQuery,
    TaskBudget,
    ThemeContribution,
)
from leisurelog.services.plugin_access import (
    PluginAccessDenied,
    PluginClassifier,
    PluginSummaryReader,
)


def manifest(capability, *permissions):
    return PluginManifest(
        "example.test", "Test", "0.1.0", ">=0.5.0a1,<0.6", 1,
        capabilities=(capability,), permissions=permissions,
    )


def event():
    now = datetime.now(timezone.utc)
    return ActivityEvent("test", "synthetic", "window", "test-device", now, now, "test.exe")


def test_public_surface_reuses_core_model_and_excludes_raw_storage_and_application():
    assert ActivityEvent is CoreEvent
    assert not {"Repository", "SourceRecord", "SQLiteRepository", "app"} & set(plugin_api.__all__)


def test_summary_permission_returns_only_detached_totals_and_supports_years():
    query = SummaryQuery(date(2020, 1, 1), date(2026, 12, 31), project_id="project")
    calls = []
    summary = ActivitySummary(120, [CategoryTotal("work", 90), CategoryTotal("game", 30)])
    provider = SimpleNamespace(read=lambda value: calls.append(value) or summary)
    reader = PluginSummaryReader(
        manifest(PluginCapability.ANALYTICS, PluginPermission.SUMMARY_READ), provider,
    )
    result = reader.read(query)
    assert calls == [query]
    assert asdict(result) == {
        "total_active_seconds": 120,
        "by_category": (
            {"category": "work", "active_seconds": 90},
            {"category": "game", "active_seconds": 30},
        ),
    }
    with pytest.raises(AttributeError):
        result.title


@pytest.mark.parametrize("change", [
    {"permissions": ()}, {"capabilities": (PluginCapability.PAGE,)},
])
def test_denied_summary_does_not_call_data_provider(change):
    calls = []
    spec = replace(manifest(PluginCapability.ANALYTICS, PluginPermission.SUMMARY_READ), **change)
    reader = PluginSummaryReader(spec, SimpleNamespace(read=lambda value: calls.append(value)))
    with pytest.raises(PluginAccessDenied):
        reader.read(SummaryQuery(date(2026, 1, 1), date(2026, 1, 1)))
    assert not calls


def test_detail_payload_cannot_be_returned_through_summary_interface():
    provider = SimpleNamespace(read=lambda value: {"title": "private", "url": "private"})
    reader = PluginSummaryReader(
        manifest(PluginCapability.ANALYTICS, PluginPermission.SUMMARY_READ), provider,
    )
    with pytest.raises(TypeError, match="ActivitySummary"):
        reader.read(SummaryQuery(date(2026, 1, 1), date(2026, 1, 1)))


def test_invalid_query_is_rejected_before_data_is_requested():
    calls = []
    reader = PluginSummaryReader(
        manifest(PluginCapability.ANALYTICS, PluginPermission.SUMMARY_READ),
        SimpleNamespace(read=lambda value: calls.append(value)),
    )
    with pytest.raises(TypeError):
        reader.read({"sql": "SELECT * FROM raw_events"})
    assert not calls


def test_classifier_cannot_impersonate_manual_override_or_return_mutable_tags():
    tags = ["sample"]
    proposal = Classification("game", "Example", tags, origin="manual")
    classifier = PluginClassifier(
        manifest(PluginCapability.CLASSIFIER,
            PluginPermission.DETAILS_READ, PluginPermission.CLASSIFICATION_PROPOSE,
        ), SimpleNamespace(classify=lambda value: proposal),
    )
    result = classifier.classify(event())
    tags.append("changed-after-call")
    assert result == Classification("game", "Example", ("sample",), "plugin:example.test@0.1.0")


def test_manual_override_skips_plugin_even_if_plugin_is_denied():
    calls = []
    classifier = PluginClassifier(
        manifest(PluginCapability.CLASSIFIER),
        SimpleNamespace(classify=lambda value: calls.append(value)),
    )
    manual = Classification("work", "Manual", origin="manual")
    assert ClassificationPipeline([classifier]).classify(event(), manual) is manual
    assert not calls


@pytest.mark.parametrize("permissions", [
    (), (PluginPermission.DETAILS_READ,), (PluginPermission.CLASSIFICATION_PROPOSE,),
])
def test_classifier_checks_read_and_propose_permissions_before_receiving_event(permissions):
    calls = []
    classifier = PluginClassifier(
        manifest(PluginCapability.CLASSIFIER, *permissions),
        SimpleNamespace(classify=lambda value: calls.append(value)),
    )
    with pytest.raises(PluginAccessDenied):
        classifier.classify(event())
    assert not calls


@pytest.mark.parametrize("proposal", [
    {"category": "game"}, Classification(""), Classification(tags="bad"),
    Classification(tags=(object(),)), Classification(content=object()),
])
def test_bad_classification_proposals_are_rejected(proposal):
    classifier = PluginClassifier(
        manifest(PluginCapability.CLASSIFIER,
            PluginPermission.DETAILS_READ, PluginPermission.CLASSIFICATION_PROPOSE,
        ), SimpleNamespace(classify=lambda value: proposal),
    )
    with pytest.raises((TypeError, ValueError)):
        classifier.classify(event())


def test_no_proposal_preserves_the_existing_classifier_fallback():
    classifier = PluginClassifier(
        manifest(PluginCapability.CLASSIFIER,
            PluginPermission.DETAILS_READ, PluginPermission.CLASSIFICATION_PROPOSE,
        ), SimpleNamespace(classify=lambda value: None),
    )
    assert ClassificationPipeline([classifier]).classify(event(), None) == Classification()


@pytest.mark.parametrize("path", [
    "../theme.css", "/theme.css", "assets/../../theme.css", "assets//theme.css",
    "assets/./theme.css", "https://example.com/theme.css", r"C:\theme.css", r"assets\theme.css",
    "theme.css?token=secret", "theme.js", "theme.css\x00",
])
def test_theme_descriptor_rejects_outside_paths_and_executable_entrypoints(path):
    with pytest.raises(ValueError):
        ThemeContribution("minimal", "Minimal", path)


def test_theme_descriptor_accepts_a_package_relative_css_resource():
    theme = ThemeContribution("minimal", "Minimal", "assets/theme.css")
    assert theme.css_path == "assets/theme.css"


@pytest.mark.parametrize("value", [float("inf"), float("nan"), -1, 0, True])
def test_task_contract_rejects_unbounded_or_invalid_stop_budgets(value):
    with pytest.raises(ValueError):
        TaskBudget(stop_timeout_seconds=value)


def test_summary_rejects_inconsistent_totals_and_non_finite_time():
    with pytest.raises(ValueError):
        ActivitySummary(100, (CategoryTotal("work", 90),))
    with pytest.raises(ValueError):
        CategoryTotal("work", float("nan"))
    with pytest.raises(ValueError):
        ActivitySummary(100, (CategoryTotal("work", 50), CategoryTotal("work", 50)))


def test_reversed_or_datetime_query_is_rejected():
    with pytest.raises(ValueError):
        SummaryQuery(date(2026, 2, 1), date(2026, 1, 1))
    with pytest.raises(ValueError):
        SummaryQuery(datetime.now(), datetime.now())
