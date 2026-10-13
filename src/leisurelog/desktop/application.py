"""Desktop settings and onboarding around the existing application composition."""

import json
from pathlib import Path
from threading import Lock
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from leisurelog import __version__
from leisurelog.adapters.scheduler import PeriodicSync
from leisurelog.desktop.paths import resources
from leisurelog.desktop.profile import DesktopPreferences
from leisurelog.desktop.security import secure_local_app
from leisurelog.main import create_app


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: bool
    initial_hours: int = 1


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class DesktopRuntime:
    def __init__(self, paths, preferences, shutdown):
        self.paths, self.preferences, self.shutdown = paths, preferences, shutdown
        self.control = Lock()
        self.app = None

    def update_sync(self, enabled, *, completed=None, initial_hours=None):
        with self.control:
            values = self.preferences.model_dump()
            values["sync_enabled"] = enabled
            if completed is not None:
                values["setup_completed"] = completed
            if initial_hours is not None:
                values["initial_hours"] = initial_hours
            updated = DesktopPreferences.model_validate(values)
            updated.save(self.paths)
            self.preferences = updated
            settings = self.app.state.settings
            settings.auto_sync_enabled = updated.setup_completed and enabled
            settings.auto_sync_initial_hours = updated.initial_hours
            old = self.app.state.scheduler
            old.stop()
            worker = PeriodicSync(old.run, old.interval, settings.auto_sync_enabled)
            self.app.state.scheduler = worker
            worker.start()
            return worker.snapshot()

    def snapshot(self):
        return {
            "version": __version__,
            "setup_completed": self.preferences.setup_completed,
            "initial_hours": self.preferences.initial_hours,
            "data_dir": str(self.paths.root),
            "activitywatch_url": self.preferences.activitywatch_url,
            "sync": self.app.state.scheduler.snapshot(),
        }

    def playnite_package(self):
        output = self.paths.root / "data/LeisureLog-Playnite.pext"
        root = resources() / "integrations/playnite"
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            archive.write(root / "extension.yaml", "extension.yaml")
            archive.writestr(
                "LeisureLog.psm1",
                (root / "LeisureLog.psm1").read_text(encoding="utf-8-sig").encode("utf-8-sig"),
            )
            archive.writestr(
                "settings.json",
                json.dumps(
                    {"export_path": str(self.paths.root / "data/playnite-library.json")},
                    ensure_ascii=False,
                ),
            )
        return output


def activitywatch_status(url):
    try:
        with httpx.Client(base_url=url, timeout=3, trust_env=False) as client:
            response = client.get("/api/0/buckets/")
            response.raise_for_status()
            buckets = response.json()
        if not isinstance(buckets, dict):
            raise ValueError("Invalid buckets")
        counts = {
            kind: sum(
                isinstance(value, dict) and value.get("type") == kind for value in buckets.values()
            )
            for kind in ("currentwindow", "afkstatus", "web.tab.current")
        }
        return {"connected": True, **counts}
    except (httpx.HTTPError, ValueError):
        return {"connected": False, "currentwindow": 0, "afkstatus": 0, "web.tab.current": 0}


def desktop_app(paths, preferences, token, origin, shutdown, *, source=None):
    app = create_app(preferences.settings(paths), source)
    runtime = DesktopRuntime(paths, preferences, shutdown)
    runtime.app = app
    app.state.desktop = runtime
    secure_local_app(app, token, origin, str(paths.root))

    @app.get("/setup", include_in_schema=False)
    def setup_page():
        return FileResponse(Path(__file__).resolve().parents[1] / "api/static/setup.html")

    @app.get("/_desktop/status", include_in_schema=False)
    def status():
        return runtime.snapshot()

    @app.get("/_desktop/activitywatch", include_in_schema=False)
    def probe():
        return activitywatch_status(runtime.preferences.activitywatch_url)

    @app.post("/_desktop/setup", include_in_schema=False)
    def finish_setup(body: SetupRequest):
        if not body.consent:
            raise HTTPException(422, "请先确认本机数据读取说明")
        if body.initial_hours not in {1, 24}:
            raise HTTPException(422, "首次导入范围只能是最近 1 小时或 24 小时")
        return runtime.update_sync(True, completed=True, initial_hours=body.initial_hours)

    @app.post("/_desktop/sync", include_in_schema=False)
    def set_sync(body: SyncRequest):
        if body.enabled and not runtime.preferences.setup_completed:
            raise HTTPException(409, "请先完成首次使用引导")
        return runtime.update_sync(body.enabled)

    @app.post("/_desktop/shutdown", include_in_schema=False)
    def stop():
        runtime.shutdown()
        return {"stopping": True}

    @app.get("/_desktop/playnite.pext", include_in_schema=False)
    def playnite():
        return FileResponse(runtime.playnite_package(), filename="LeisureLog-Playnite.pext")

    return app
