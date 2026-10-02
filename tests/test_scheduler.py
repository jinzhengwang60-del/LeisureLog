from threading import Event

from leisurelog.adapters.scheduler import PeriodicSync


def test_worker_retries_and_stops():
    attempts = []
    recovered = Event()

    def run(stop):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("offline")
        recovered.set()
        return {"changed": 2}

    worker = PeriodicSync(run, interval_seconds=0.01, enabled=True)
    worker.start()
    try:
        assert recovered.wait(2)
    finally:
        worker.stop()
    assert not worker.thread.is_alive()
    status = worker.snapshot()
    assert status["last_error"] is None
    assert status["last_result"] == {"changed": 2}
    assert not status["running"]


def test_disabled_worker_does_not_run():
    def unexpected(stop):
        raise AssertionError("disabled worker ran")

    worker = PeriodicSync(unexpected, 60, False)
    worker.start()
    worker.stop()
    assert worker.thread is None
    assert worker.snapshot()["last_attempt_at"] is None
