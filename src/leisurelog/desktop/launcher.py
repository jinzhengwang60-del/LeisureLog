"""Single-process desktop launcher, migrations, reserved socket and graceful shutdown."""

import argparse
import json
import logging
import os
import secrets
import socket
import sys
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Event, Thread
from urllib.parse import urlencode, urlsplit

import httpx

from leisurelog.desktop.application import desktop_app
from leisurelog.desktop.database import prepare_database
from leisurelog.desktop.instance import InstanceLock
from leisurelog.desktop.paths import DesktopPaths, default_data_dir
from leisurelog.desktop.profile import DesktopPreferences, write_json

logger = logging.getLogger(__name__)


def reserve_socket(port):
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        connection.bind(("127.0.0.1", port))
    except OSError:
        if not port:
            connection.close()
            raise
        connection.bind(("127.0.0.1", 0))
    connection.listen(128)
    return connection


def running_instance(paths):
    try:
        value = json.loads(paths.runtime.read_text(encoding="utf-8"))
        address = urlsplit(value["url"])
        if address.scheme != "http" or address.hostname != "127.0.0.1" or not address.port:
            return None
        with httpx.Client(timeout=2, trust_env=False) as client:
            response = client.get(
                value["url"] + "/_desktop/status",
                headers={"Authorization": "Bearer " + value["token"]},
            )
        response.raise_for_status()
        if response.json()["data_dir"] != str(paths.root):
            return None
        return value
    except (OSError, ValueError, KeyError, httpx.HTTPError):
        return None


def browser_url(instance):
    return instance["url"] + "/_desktop/open?" + urlencode({"token": instance["token"]})


def configure_logging(paths):
    handler = RotatingFileHandler(
        paths.root / "logs/desktop.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    # A windowed executable has no stdout/stderr; errors still belong in local files.
    if sys.stdout is None:
        sys.stdout = open(paths.root / "logs/console.log", "a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.stdout


def serve(paths, preferences, args):
    import uvicorn

    socket_handle = reserve_socket(args.port if args.port is not None else preferences.web_port)
    preferences = preferences.model_copy(update={"web_port": socket_handle.getsockname()[1]})
    preferences.save(paths)
    origin = f"http://127.0.0.1:{socket_handle.getsockname()[1]}"
    instance = {"url": origin, "token": secrets.token_urlsafe(32), "pid": os.getpid()}
    server = None
    finished = Event()
    tray = []

    def shutdown():
        server.should_exit = True

    app = desktop_app(paths, preferences, instance["token"], origin, shutdown)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=socket_handle.getsockname()[1],
            loop="asyncio",
            http="h11",
            ws="none",
            log_config=None,
            access_log=False,
            timeout_graceful_shutdown=30,
        )
    )

    def open_page(destination=None):
        # Bootstrap resets the session without leaving its secret in the final address.
        url = browser_url(instance)
        if destination == "/setup":
            url += "&page=setup"
        webbrowser.open(url)

    def ready():
        while not server.started:
            if finished.wait(0.1):
                return
        write_json(paths.runtime, instance)
        if os.name == "nt" and not args.no_tray:
            try:
                from leisurelog.desktop.tray import start_tray

                tray.append(start_tray(app.state.desktop, open_page))
            except Exception:
                logger.exception("System tray could not start; local settings remain available")
        if not args.no_browser:
            open_page()

    starter = Thread(target=ready, name="leisurelog-ready", daemon=True)
    starter.start()
    try:
        server.run(sockets=[socket_handle])
    finally:
        finished.set()
        starter.join(5)
        for icon in tray:
            icon.stop()
        socket_handle.close()
        paths.runtime.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="LeisureLog Windows 本地安装版")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--activitywatch-url")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    if args.port is not None and not 0 <= args.port <= 65535:
        parser.error("端口范围是 0–65535")
    paths = DesktopPaths(args.data_dir.expanduser().resolve())
    if args.stop or args.status:
        instance = running_instance(paths)
        if instance and args.stop:
            with httpx.Client(timeout=5, trust_env=False) as client:
                response = client.post(
                    instance["url"] + "/_desktop/shutdown",
                    headers={"Authorization": "Bearer " + instance["token"]},
                )
                response.raise_for_status()
        if sys.stdout:
            print("LeisureLog 正在运行" if instance else "LeisureLog 未运行")
        return 0 if instance or args.stop else 1
    lock = InstanceLock(paths.root)
    owned = False
    try:
        owned = lock.acquire()
        if not owned:
            # A first launch may still be migrating; wait for that owner rather than starting two.
            for _ in range(100):
                instance = running_instance(paths)
                if instance:
                    if not args.no_browser:
                        webbrowser.open(browser_url(instance))
                    return 0
                time.sleep(0.1)
            raise RuntimeError("LeisureLog 正在启动或退出，请稍后再打开")
        paths.prepare()
        configure_logging(paths)
        preferences = DesktopPreferences.load(paths)
        if args.activitywatch_url:
            preferences = DesktopPreferences.model_validate(
                {**preferences.model_dump(), "activitywatch_url": args.activitywatch_url}
            )
            preferences.save(paths)
        prepare_database(paths)
        serve(paths, preferences, args)
        return 0
    except Exception:
        logger.exception("Desktop startup failed")
        if os.name == "nt" and not args.no_tray:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                "LeisureLog 未能启动。已有记录不会被删除。\n请查看："
                + str(paths.root / "logs/desktop.log"),
                "LeisureLog",
                0x10,
            )
        return 1
    finally:
        lock.close()
