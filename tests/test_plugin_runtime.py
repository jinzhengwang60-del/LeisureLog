"""Real owned threads, revocation and dependency failure, using synthetic providers."""

from dataclasses import replace
from datetime import date, datetime, timezone
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest

from leisurelog.adapters.plugin_workers import ThreadPluginWorkers
from leisurelog.domain.classification import ClassificationPipeline
from leisurelog.domain.models import ActivityEvent, Classification
from leisurelog.domain.plugin_contracts import ActivitySummary, SummaryQuery, TaskBudget
from leisurelog.domain.plugin_runtime import (
    PluginConfiguration,
    PluginContributions,
    PluginDefinition,
    ScheduledTask,
)
from leisurelog.domain.plugins import PluginCapability as Capability
from leisurelog.domain.plugins import PluginDependency, PluginManifest
from leisurelog.domain.plugins import PluginPermission as Permission
from leisurelog.repositories.plugin_state import FilePluginState
from leisurelog.services.plugin_access import PluginAccessDenied
from leisurelog.services.plugin_runtime import PluginOperationError, PluginRuntime


def definition(
    name="example.test", *, create=None, caps=(), permissions=(), dependencies=(), priority=100
):
    return PluginDefinition(
        PluginManifest(
            name,
            name,
            "0.1.0",
            ">=0.4.0b1,<0.6",
            1,
            caps,
            permissions,
            dependencies,
        ),
        create or (lambda context: PluginContributions()),
        priority,
    )


def activity():
    now = datetime.now(timezone.utc)
    return ActivityEvent("synthetic", "test", "window", "test-pc", now, now, "unknown.exe")


def eventually(check):
    deadline = monotonic() + 2
    pause = Event()
    while not check():
        assert monotonic() < deadline, "worker did not reach the expected state"
        pause.wait(0.005)


def status(runtime, name="example.test"):
    return next(value for value in runtime.snapshot()["plugins"] if value["id"] == name)


@pytest.fixture
def host(tmp_path):
    instances, releases = [], []

    def create(definitions, *, store=None, provider=None, **kwargs):
        workers = ThreadPluginWorkers(max_workers=kwargs.pop("max_workers", 16))
        runtime = PluginRuntime(
            tuple(definitions),
            workers,
            store or FilePluginState(tmp_path / "plugins.json"),
            provider or SimpleNamespace(read=lambda query: ActivitySummary(0)),
            app_version="0.4.0b1",
            call_timeout=0.08,
            startup_timeout=0.5,
            stop_timeout=0.08,
            **kwargs,
        )
        instances.append((runtime, workers))
        runtime.start()
        return runtime, workers

    create.releases = releases
    yield create
    for release in releases:
        release.set()
    for runtime, workers in instances:
        runtime.close()
        workers.close(2)


def test_enable_is_idempotent_and_tasks_are_owned_serial_and_stoppable(host):
    started = Event()
    owners = []

    def run(context):
        owners.append(context.owner_plugin_id)
        started.set()
        context.wait_for_stop(0.02)

    plugin = definition(
        caps=(Capability.TASK,),
        create=lambda context: PluginContributions(
            tasks=(ScheduledTask("probe", SimpleNamespace(run=run), 0.01),)
        ),
    )
    runtime, workers = host([plugin])
    runtime.enable("example.test")
    assert started.wait(1)
    revision = runtime.snapshot()["revision"]
    runtime.enable("example.test")
    assert runtime.snapshot()["revision"] == revision
    assert (
        len([value for value in workers.snapshot("example.test") if value["kind"] == "task"]) == 1
    )
    assert set(owners) == {"example.test"}
    runtime.disable("example.test")
    assert status(runtime)["state"] == "disabled"
    assert not workers.busy("example.test")


def test_old_reader_stays_revoked_after_disable_and_new_activation(host):
    readers, calls = [], []
    spec = definition(
        caps=(Capability.ANALYTICS,),
        permissions=(Permission.SUMMARY_READ,),
        create=lambda context: readers.append(context.summary) or PluginContributions(),
    )
    runtime, _ = host(
        [spec],
        provider=SimpleNamespace(
            read=lambda query: calls.append(query) or ActivitySummary(0),
        ),
    )
    grant = {"example.test": (Permission.SUMMARY_READ,)}
    runtime.enable("example.test", grant)
    query = SummaryQuery(date(2020, 1, 1), date(2026, 12, 31))
    readers[0].read(query)
    runtime.revoke("example.test", Permission.SUMMARY_READ)
    with pytest.raises(PluginAccessDenied):
        readers[0].read(query)
    assert len(calls) == 1
    with pytest.raises(PluginOperationError) as error:
        runtime.enable("example.test")
    assert error.value.issue.code == "permission_required"
    runtime.enable("example.test", grant)
    readers[1].read(query)
    with pytest.raises(PluginAccessDenied):
        readers[0].read(query)
    assert len(calls) == 2


def test_revocation_discards_an_in_flight_read_and_defers_shared_resource_cleanup(host):
    entered, release, cleaned = Event(), Event(), Event()
    host.releases.append(release)

    def read(query):
        entered.set()
        release.wait(2)
        return ActivitySummary(0)

    def create(context):
        return PluginContributions(
            tasks=(
                ScheduledTask(
                    "read",
                    SimpleNamespace(
                        run=lambda task_context: context.summary.read(
                            SummaryQuery(date(2026, 1, 1), date(2026, 1, 1))
                        ),
                    ),
                    budget=TaskBudget(2, 0.08),
                ),
            )
        )

    plugin = definition(
        caps=(Capability.ANALYTICS, Capability.TASK),
        permissions=(Permission.SUMMARY_READ,),
        create=create,
    )
    runtime, workers = host([plugin], provider=SimpleNamespace(read=read))
    runtime.enable("example.test", {"example.test": (Permission.SUMMARY_READ,)})
    assert entered.wait(1)
    runtime.revoke("example.test", Permission.SUMMARY_READ)
    assert status(runtime)["last_error"]["code"] == "stop_timeout"
    assert runtime.close() is False
    runtime.when_drained(cleaned.set)
    assert not cleaned.is_set()
    release.set()
    assert cleaned.wait(1)
    eventually(lambda: not workers.busy("example.test"))
    assert all(
        value["completed_runs"] == 0
        for value in workers.snapshot("example.test")
        if value["kind"] == "task"
    )


def test_noncooperative_timeout_retains_slot_and_prevents_duplicate_workers(host):
    entered, release = Event(), Event()
    host.releases.append(release)

    def run(context):
        entered.set()
        release.wait(2)

    plugin = definition(
        caps=(Capability.TASK,),
        create=lambda context: PluginContributions(
            tasks=(
                ScheduledTask("blocked", SimpleNamespace(run=run), budget=TaskBudget(0.05, 0.02)),
            )
        ),
    )
    runtime, workers = host([plugin])
    runtime.enable("example.test")
    assert entered.wait(1)
    eventually(lambda: status(runtime)["state"] == "failed")
    assert status(runtime)["last_error"]["code"] == "task_timeout"
    assert workers.busy("example.test")
    for _ in range(3):
        with pytest.raises(PluginOperationError) as error:
            runtime.enable("example.test")
        assert error.value.issue.code == "workers_still_running"
    assert (
        len([value for value in workers.snapshot("example.test") if value["kind"] == "task"]) == 1
    )
    release.set()
    eventually(lambda: not workers.busy("example.test"))
    runtime.disable("example.test")


def test_dependency_disable_requires_cascade_and_revoke_stops_dependents(host):
    base = definition(
        "example.base", caps=(Capability.ANALYTICS,), permissions=(Permission.SUMMARY_READ,)
    )
    child = definition("example.child", dependencies=(PluginDependency("example.base", ">=0.1"),))
    runtime, _ = host([base, child])
    runtime.enable("example.child", {"example.base": (Permission.SUMMARY_READ,)})
    assert status(runtime, "example.base")["state"] == "running"
    with pytest.raises(PluginOperationError) as error:
        runtime.disable("example.base")
    assert error.value.issue.code == "dependents_active"
    runtime.revoke("example.base", Permission.SUMMARY_READ)
    assert all(value["state"] == "disabled" for value in runtime.snapshot()["plugins"])
    assert not any(value["enabled"] for value in runtime.snapshot()["plugins"])


def test_task_failure_withdraws_dependents_but_keeps_unrelated_plugin_running(host):
    trigger = Event()

    def run(context):
        trigger.wait(1)
        raise RuntimeError("private window title / sensitive URL")

    base = definition(
        "example.base",
        caps=(Capability.TASK,),
        create=lambda context: PluginContributions(
            tasks=(ScheduledTask("probe", SimpleNamespace(run=run)),)
        ),
    )
    child = definition("example.child", dependencies=(PluginDependency("example.base", ">=0.1"),))
    other = definition("example.other")
    runtime, _ = host([base, child, other])
    runtime.enable("example.child")
    runtime.enable("example.other")
    trigger.set()
    eventually(lambda: status(runtime, "example.base")["state"] == "failed")
    assert status(runtime, "example.child")["last_error"]["code"] == "dependency_failed"
    assert status(runtime, "example.other")["state"] == "running"
    assert "sensitive" not in str(runtime.snapshot())


def test_factory_failure_rolls_back_new_dependencies_without_changing_previous_selection(host):
    created = []
    base = definition(
        "example.base", create=lambda context: created.append(context) or PluginContributions()
    )

    def broken(context):
        raise RuntimeError("private details")

    bad = definition(
        "example.bad", create=broken, dependencies=(PluginDependency("example.base", ">=0.1"),)
    )
    other = definition("example.other")
    runtime, _ = host([base, bad, other])
    runtime.enable("example.other")
    revision = runtime.snapshot()["revision"]
    with pytest.raises(PluginOperationError):
        runtime.enable("example.bad")
    assert runtime.snapshot()["revision"] == revision
    assert status(runtime, "example.base")["state"] == "disabled"
    assert status(runtime, "example.other")["state"] == "running"
    assert not status(runtime, "example.bad")["enabled"]


def test_persistence_failure_does_not_start_tasks_or_change_running_selection(
    host, tmp_path, monkeypatch
):
    store = FilePluginState(tmp_path / "state.json")
    attempts = []
    one = definition("example.one")
    two = definition(
        "example.two",
        caps=(Capability.TASK,),
        create=lambda context: PluginContributions(
            tasks=(
                ScheduledTask("probe", SimpleNamespace(run=lambda context: attempts.append(True))),
            ),
        ),
    )
    runtime, _ = host([one, two], store=store)
    runtime.enable("example.one")
    saved = store.path.read_bytes()
    monkeypatch.setattr(
        store, "save", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk"))
    )
    with pytest.raises(PluginOperationError) as error:
        runtime.enable("example.two")
    assert error.value.issue.code == "configuration_write_failed"
    assert not attempts
    assert store.path.read_bytes() == saved
    assert status(runtime, "example.one")["state"] == "running"
    assert status(runtime, "example.two")["state"] == "disabled"
    with pytest.raises(PluginOperationError):
        runtime.disable("example.one")
    assert status(runtime, "example.one")["state"] == "running"


def test_restart_restores_only_saved_intent_and_once_per_failed_dependency(host, tmp_path):
    store = FilePluginState(tmp_path / "restore.json")
    calls = []
    base = definition(
        "example.base", create=lambda context: calls.append("base") or PluginContributions()
    )
    child = definition("example.child", dependencies=(PluginDependency("example.base", ">=0.1"),))
    good = definition("example.good")
    runtime, _ = host([base, child, good], store=store)
    runtime.enable("example.child")
    runtime.enable("example.good")
    runtime.close()

    def fail(context):
        calls.append("broken")
        raise RuntimeError("failure")

    updated = replace(base, create=fail)
    resumed, _ = host([updated, child, good], store=store)
    assert calls.count("broken") == 1
    assert status(resumed, "example.child")["state"] == "unavailable"
    assert status(resumed, "example.good")["state"] == "running"
    resumed.start()
    assert calls.count("broken") == 1


def test_corrupt_config_remains_preserved_and_blocks_mutation_not_core(host, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"not": "valid"}', encoding="utf-8")
    runtime, _ = host([definition()], store=FilePluginState(path))
    assert runtime.snapshot()["configuration_error"]["code"] == "configuration_invalid"
    with pytest.raises(PluginOperationError):
        runtime.enable("example.test")
    assert path.read_text(encoding="utf-8") == '{"not": "valid"}'
    assert runtime.classify(activity()) is None


def test_classifier_priority_is_explicit_and_manual_override_never_calls_plugins(host):
    calls = []
    permissions = (Permission.DETAILS_READ, Permission.CLASSIFICATION_PROPOSE)

    def plugin(name, priority):
        return definition(
            name,
            priority=priority,
            caps=(Capability.CLASSIFIER,),
            permissions=permissions,
            create=lambda context: PluginContributions(
                classifiers=(
                    SimpleNamespace(
                        classify=lambda value: (
                            calls.append(name) or Classification("work", name, origin="manual")
                        )
                    ),
                )
            ),
        )

    runtime, _ = host([plugin("example.last", 200), plugin("example.first", 10)])
    runtime.enable("example.last", {"example.last": permissions})
    runtime.enable("example.first", {"example.first": permissions})
    pipeline = ClassificationPipeline([runtime])
    manual = Classification("game", origin="manual")
    assert pipeline.classify(activity(), manual) is manual
    assert not calls
    result = pipeline.classify(activity(), None)
    assert result.content == "example.first"
    assert result.origin == "plugin:example.first@0.1.0"
    assert calls == ["example.first"]


def test_classifier_timeout_returns_fallback_and_discards_late_result(host):
    release = Event()
    host.releases.append(release)

    def classify(value):
        release.wait(2)
        return Classification("work", "late")

    permissions = (Permission.DETAILS_READ, Permission.CLASSIFICATION_PROPOSE)
    plugin = definition(
        caps=(Capability.CLASSIFIER,),
        permissions=permissions,
        create=lambda context: PluginContributions(
            classifiers=(SimpleNamespace(classify=classify),)
        ),
    )
    runtime, workers = host([plugin])
    runtime.enable("example.test", {"example.test": permissions})
    assert ClassificationPipeline([runtime]).classify(activity(), None) == Classification()
    assert status(runtime)["last_error"]["code"] == "call_timeout"
    assert workers.busy("example.test")
    release.set()
    eventually(lambda: not workers.busy("example.test"))
    assert runtime.classify(activity()) is None


def test_stale_revision_and_undeclared_contribution_are_rejected(host):
    plugin = definition(
        create=lambda context: PluginContributions(
            classifiers=(SimpleNamespace(classify=lambda value: None),),
        )
    )
    runtime, _ = host([plugin])
    with pytest.raises(PluginOperationError) as error:
        runtime.enable("example.test")
    assert error.value.issue.code == "invalid_contribution"
    with pytest.raises(PluginOperationError) as error:
        runtime.enable("example.test", expected_revision=4)
    assert error.value.issue.code == "configuration_conflict"


def test_worker_limit_preserves_existing_plugin_and_recovers_after_release(host):
    entered = Event()
    one = definition(
        "example.one",
        caps=(Capability.TASK,),
        create=lambda context: PluginContributions(
            tasks=(
                ScheduledTask(
                    "probe",
                    SimpleNamespace(run=lambda context: entered.set()),
                ),
            )
        ),
    )
    two = definition("example.two")
    runtime, _ = host([one, two], max_workers=1)
    runtime.enable("example.one")
    assert entered.wait(1)
    with pytest.raises(PluginOperationError) as error:
        runtime.enable("example.two")
    assert error.value.issue.code == "worker_limit"
    assert status(runtime, "example.one")["state"] == "running"
    assert not status(runtime, "example.two")["enabled"]
    runtime.disable("example.one")
    runtime.enable("example.two")
    assert status(runtime, "example.two")["state"] == "running"


def test_factory_timeout_cannot_be_retried_while_old_factory_is_still_running(host):
    release = Event()
    host.releases.append(release)
    attempts = []

    def create(context):
        attempts.append(True)
        release.wait(2)
        return PluginContributions()

    runtime, workers = host([definition(create=create)])
    with pytest.raises(PluginOperationError) as error:
        runtime.enable("example.test")
    assert error.value.issue.code == "call_timeout"
    assert status(runtime)["state"] == "failed"
    assert runtime.snapshot()["revision"] == 0
    with pytest.raises(PluginOperationError) as error:
        runtime.enable("example.test")
    assert error.value.issue.code == "workers_still_running"
    assert attempts == [True]
    release.set()
    eventually(lambda: not workers.busy("example.test"))


def test_removed_package_is_reported_without_breaking_other_saved_plugins(host, tmp_path):
    store = FilePluginState(tmp_path / "orphan.json")
    store.save(
        PluginConfiguration(1, {"example.missing": (), "example.good": ()}), expected_revision=0
    )
    runtime, _ = host([definition("example.good")], store=store)
    assert status(runtime, "example.good")["state"] == "running"
    assert status(runtime, "example.missing")["state"] == "unavailable"
    runtime.disable("example.missing")
    assert "example.missing" not in store.load().enabled
    assert status(runtime, "example.good")["state"] == "running"


def test_delayed_failure_notification_cannot_disable_a_new_generation(host):
    delayed, release, notified = Event(), Event(), Event()
    host.releases.append(release)
    attempts = []

    def create(context):
        attempts.append(True)
        if len(attempts) > 1:
            return PluginContributions()
        return PluginContributions(
            tasks=(
                ScheduledTask(
                    "probe",
                    SimpleNamespace(
                        run=lambda context: context.wait_for_stop(1),
                    ),
                    budget=TaskBudget(0.05, 0.1),
                ),
            )
        )

    runtime, workers = host([definition(create=create, caps=(Capability.TASK,))])

    def notify(owner, generation, code):
        delayed.set()
        release.wait(2)
        runtime._fault(owner, generation, code)
        notified.set()

    workers.set_failure_handler(notify)
    runtime.enable("example.test")
    assert delayed.wait(1)
    eventually(lambda: not workers.busy("example.test"))
    runtime.disable("example.test")
    runtime.enable("example.test")
    release.set()
    assert notified.wait(1)
    assert status(runtime)["state"] == "running"


def test_task_named_call_does_not_collide_with_classifier_execution(host):
    permissions = (Permission.DETAILS_READ, Permission.CLASSIFICATION_PROPOSE)
    plugin = definition(
        caps=(Capability.TASK, Capability.CLASSIFIER),
        permissions=permissions,
        create=lambda context: PluginContributions(
            tasks=(ScheduledTask("call", SimpleNamespace(run=lambda context: None)),),
            classifiers=(SimpleNamespace(classify=lambda value: Classification("work")),),
        ),
    )
    runtime, _ = host([plugin])
    runtime.enable("example.test", {"example.test": permissions})
    assert runtime.classify(activity()).category == "work"
    assert status(runtime)["state"] == "running"


def test_classifier_chain_shares_one_budget_instead_of_waiting_for_every_plugin(host):
    calls = []
    pause = Event()
    permissions = (Permission.DETAILS_READ, Permission.CLASSIFICATION_PROPOSE)

    def plugin(name, slow):
        def classify(value):
            calls.append(name)
            if slow:
                pause.wait(0.06)
                return None
            return Classification("work")

        return definition(
            name,
            caps=(Capability.CLASSIFIER,),
            permissions=permissions,
            create=lambda context: PluginContributions(
                classifiers=(SimpleNamespace(classify=classify),)
            ),
        )

    runtime, _ = host(
        [
            plugin("example.first", True),
            plugin("example.second", True),
            plugin("example.third", False),
        ]
    )
    for name in ("example.first", "example.second", "example.third"):
        runtime.enable(name, {name: permissions})
    assert runtime.classify(activity()) is None
    assert "example.third" not in calls
