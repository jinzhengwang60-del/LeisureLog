"""A single serial worker, owned and stopped by the application lifespan."""

import logging
from datetime import datetime, timezone
from threading import Event, Lock, Thread

logger = logging.getLogger(__name__)


class PeriodicSync:
    def __init__(self, run, interval_seconds: float, enabled: bool):
        self.run = run
        self.interval = interval_seconds
        self.enabled = enabled
        self.stop_event = Event()
        self.lock = Lock()
        self.thread = None
        self.state = {
            "enabled": enabled,
            "running": False,
            "interval_seconds": interval_seconds,
            "last_attempt_at": None,
            "last_success_at": None,
            "last_result": None,
            "last_error": None,
        }

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def tick(self):
        with self.lock:
            self.state.update(running=True, last_attempt_at=datetime.now(timezone.utc))
        try:
            result = self.run(self.stop_event)
            with self.lock:
                self.state.update(
                    last_success_at=datetime.now(timezone.utc),
                    last_result=result,
                    last_error=None,
                )
        except Exception:
            # Do not expose source payloads or private window titles in the status API.
            logger.exception("Automatic ActivityWatch sync failed; will retry next interval")
            with self.lock:
                self.state["last_error"] = "Sync failed; check ActivityWatch and database migration"
        finally:
            with self.lock:
                self.state["running"] = False

    def _loop(self):
        while not self.stop_event.is_set():
            self.tick()
            if self.stop_event.wait(self.interval):
                break

    def start(self):
        if self.enabled:
            self.thread = Thread(target=self._loop, name="leisurelog-sync", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()
