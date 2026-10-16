"""Bounded, owned cooperative workers; timed-out threads retain their slots."""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import TIMEOUT_MAX, Event, Lock, Thread
from time import monotonic

from leisurelog.domain.plugin_contracts import TaskStopResult
from leisurelog.domain.plugin_runtime import PluginExecutionError, ScheduledTask

logger = logging.getLogger(__name__)


def _timeout(value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and 0 <= value <= TIMEOUT_MAX
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("等待时间超出宿主支持的范围")
    return float(value)


@dataclass
class _Work:
    owner: str
    generation: int
    name: str
    kind: str
    stop: Event = field(default_factory=Event)
    thread: Thread | None = None
    deadline: float | None = None
    error: str | None = None
    completed_runs: int = 0
    finished: bool = False
    result: object = None
    stop_budget: float | None = None
    stop_deadline: float | None = None


class _TaskContext:
    def __init__(self, job: _Work):
        self._owner = job.owner
        self._stop = job.stop

    @property
    def owner_plugin_id(self):
        return self._owner

    def stop_requested(self):
        return self._stop.is_set()

    def wait_for_stop(self, timeout_seconds):
        return self._stop.wait(_timeout(timeout_seconds))


class ThreadPluginWorkers:
    def __init__(self, *, max_workers: int = 32):
        if type(max_workers) is not int or not 1 <= max_workers <= 128:
            raise ValueError("插件工作线程上限必须在 1–128 之间")
        self._maximum = max_workers
        self._jobs = {}
        self._lock = Lock()
        self._closed = False
        self._watch_stop = Event()
        self._watcher = None
        self._handler = lambda owner, generation, code: None
        self._cleanup: list[Callable] = []

    def set_failure_handler(self, handler):
        self._handler = handler

    def check_capacity(self, additional):
        with self._lock:
            if self._closed:
                raise PluginExecutionError("host_closed")
            if sum(not job.finished for job in self._jobs.values()) + additional > self._maximum:
                raise PluginExecutionError("worker_limit")

    def _spawn(self, job, run):
        with self._lock:
            if self._closed:
                raise PluginExecutionError("host_closed")
            active = [value for value in self._jobs.values() if not value.finished]
            if len(active) >= self._maximum:
                raise PluginExecutionError("worker_limit")
            if job.kind == "call" and any(
                value.owner == job.owner and value.kind == "call" and value.name == job.name
                for value in active
            ):
                raise PluginExecutionError("call_busy")
            key = (job.owner, job.generation, job.kind, job.name)
            previous = self._jobs.get(key)
            if previous and previous.thread and previous.thread.is_alive():
                raise PluginExecutionError("worker_busy")
            job.thread = Thread(
                target=run,
                name=f"plugin-{job.owner}-{job.kind}-{job.name}",
                daemon=True,
            )
            self._jobs[key] = job
            if self._watcher is None:
                self._watcher = Thread(target=self._watch, name="plugin-watchdog", daemon=True)
                self._watcher.start()
        try:
            job.thread.start()
        except RuntimeError:
            self._retire(job)
            raise PluginExecutionError("worker_start_failed") from None

    def _fail(self, job, code):
        with self._lock:
            if job.error is not None:
                return
            if code.endswith("timeout") and (
                job.finished or job.deadline is None or monotonic() < job.deadline
            ):
                return
            job.error = code
            job.stop.set()
        # Never include plugin exception text, which can contain URLs and private titles.
        logger.warning("Plugin %s failed: %s", job.owner, code)
        self._handler(job.owner, job.generation, code)

    def _retire(self, job):
        with self._lock:
            job.finished = True
            job.deadline = None
            callbacks = []
            if all(value.finished for value in self._jobs.values()):
                callbacks, self._cleanup = self._cleanup, []
        for callback in callbacks:
            callback()

    def _watch(self):
        while not self._watch_stop.wait(0.02):
            with self._lock:
                expired = [
                    job
                    for job in self._jobs.values()
                    if job.deadline is not None
                    and monotonic() >= job.deadline
                    and job.error is None
                    and not job.finished
                ]
            for job in expired:
                self._fail(job, "call_timeout" if job.kind == "call" else "task_timeout")

    def call(self, owner, generation, run, timeout, *, channel="call"):
        timeout = _timeout(timeout)
        if channel not in {"call", "metadata", "analysis"}:
            raise ValueError("宿主仅提供分类/启动、资料与分析调用通道")
        deadline = monotonic() + timeout
        job = _Work(owner, generation, channel, "call", deadline=deadline)

        def invoke():
            try:
                value = run()
                if monotonic() >= job.deadline:
                    self._fail(job, "call_timeout")
                elif job.error is None:
                    job.result = value
                    job.completed_runs = 1
            except BaseException:
                self._fail(job, "call_exception")
            finally:
                self._retire(job)

        self._spawn(job, invoke)
        # A timed join can wake before our clock reaches the deadline, notably
        # with Windows' coarse monotonic clock on Python 3.11. Never return an
        # unfinished call's empty result; wait for completion or a real timeout.
        while job.thread.is_alive():
            remaining = deadline - monotonic()
            if remaining <= 0:
                self._fail(job, "call_timeout")
                break
            job.thread.join(remaining)
        if job.error:
            raise PluginExecutionError(job.error)
        return job.result

    def start(self, owner, generation, task: ScheduledTask):
        run_timeout = _timeout(task.budget.run_timeout_seconds)
        stop_budget = _timeout(task.budget.stop_timeout_seconds)
        job = _Work(owner, generation, task.name, "task", stop_budget=stop_budget)

        def repeat():
            context = _TaskContext(job)
            try:
                while not job.stop.is_set():
                    with self._lock:
                        job.deadline = monotonic() + run_timeout
                    try:
                        task.task.run(context)
                        if monotonic() >= job.deadline:
                            self._fail(job, "task_timeout")
                        elif job.error is None:
                            job.completed_runs += 1
                    except BaseException:
                        self._fail(job, "task_exception")
                    finally:
                        with self._lock:
                            job.deadline = None
                    if job.stop.wait(task.interval_seconds):
                        break
            finally:
                self._retire(job)

        self._spawn(job, repeat)

    def request_stop(self, owner):
        with self._lock:
            for job in self._jobs.values():
                if job.owner == owner:
                    if job.stop_deadline is None and job.stop_budget is not None:
                        job.stop_deadline = monotonic() + job.stop_budget
                    job.stop.set()

    def wait_stopped(self, owner, timeout):
        deadline = monotonic() + _timeout(timeout)
        with self._lock:
            jobs = [job for job in self._jobs.values() if job.owner == owner and job.thread]
        for job in jobs:
            limit = min(deadline, job.stop_deadline or deadline)
            job.thread.join(max(0, limit - monotonic()))
            if job.thread.is_alive():
                return TaskStopResult.TIMED_OUT
        return TaskStopResult.TIMED_OUT if self.busy(owner) else TaskStopResult.STOPPED

    def busy(self, owner):
        with self._lock:
            return any(
                job.owner == owner and job.thread and job.thread.is_alive()
                for job in self._jobs.values()
            )

    def forget(self, owner):
        with self._lock:
            self._jobs = {
                key: job
                for key, job in self._jobs.items()
                if job.owner != owner or not job.finished or (job.thread and job.thread.is_alive())
            }

    def snapshot(self, owner):
        with self._lock:
            return [
                {
                    "name": job.name,
                    "kind": job.kind,
                    "generation": job.generation,
                    "running": bool(job.thread and job.thread.is_alive()),
                    "stop_requested": job.stop.is_set(),
                    "error": job.error,
                    "completed_runs": job.completed_runs,
                }
                for job in self._jobs.values()
                if job.owner == owner
            ]

    def close(self, timeout):
        deadline = monotonic() + _timeout(timeout)
        with self._lock:
            self._closed = True
            owners = {job.owner for job in self._jobs.values()}
        for owner in owners:
            self.request_stop(owner)
        for owner in owners:
            self.wait_stopped(owner, max(0, deadline - monotonic()))
        self._watch_stop.set()
        if self._watcher:
            self._watcher.join(max(0, deadline - monotonic()))
        return not any(self.busy(owner) for owner in owners)

    def when_drained(self, callback):
        with self._lock:
            if not self._closed:
                raise ValueError("释放共享资源前必须关闭插件宿主")
            ready = all(job.finished for job in self._jobs.values())
            if not ready:
                self._cleanup.append(callback)
        if ready:
            callback()
