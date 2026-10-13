"""Exercise a built executable through real HTTP, with synthetic sources and isolated data."""

import argparse
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx


class FakeActivityWatch(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/0/buckets/":
            body = {
                "window": {"type": "currentwindow", "hostname": "installation-test"},
                "afk": {"type": "afkstatus", "hostname": "installation-test"},
            }
        elif "/events" in path:
            begin = datetime.now(timezone.utc) - timedelta(minutes=3)
            data = (
                {"status": "not-afk"}
                if "/afk/" in path
                else {"app": "synthetic-editor.exe", "title": "Installation verification sample"}
            )
            body = [{"id": 1, "timestamp": begin.isoformat(), "duration": 150, "data": data}]
        else:
            self.send_error(404)
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def wait_instance(process, profile):
    for _ in range(150):
        if process.poll() is not None:
            log = profile / "logs/desktop.log"
            raise RuntimeError(
                f"Executable exited with {process.returncode}: "
                + (log.read_text(encoding="utf-8")[-5000:] if log.exists() else "no log")
            )
        try:
            value = json.loads((profile / "runtime.json").read_text(encoding="utf-8"))
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.get(
                    value["url"] + "/_desktop/status",
                    headers={"Authorization": "Bearer " + value["token"]},
                )
            if response.status_code == 200:
                return value
        except (OSError, ValueError, httpx.HTTPError):
            pass
        time.sleep(0.2)
    raise RuntimeError("Executable did not become ready")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--with-tray", action="store_true")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    profile = workspace / "试用用户 100%" / "LeisureLog"
    environment = dict(os.environ)
    for name in ("PYTHONHOME", "PYTHONPATH", "LEISURELOG_DATABASE_URL", "LEISURELOG_RULES_PATH"):
        environment.pop(name, None)
    environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    source = ThreadingHTTPServer(("127.0.0.1", 0), FakeActivityWatch)
    threading.Thread(target=source.serve_forever, daemon=True).start()
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    command = [
        str(args.exe.resolve()),
        "--data-dir",
        str(profile),
        "--no-browser",
        "--port",
        str(occupied.getsockname()[1]),
        "--activitywatch-url",
        f"http://127.0.0.1:{source.server_port}",
    ]
    if not args.with_tray:
        command.append("--no-tray")
    process = None
    evidence = {"executable": str(args.exe.resolve()), "profile": str(profile), "checks": []}
    try:
        process = subprocess.Popen(command, cwd=workspace, env=environment)
        instance = wait_instance(process, profile)
        assert urlsplit(instance["url"]).port != occupied.getsockname()[1]
        evidence["checks"].append("occupied port selects another loopback port")
        with httpx.Client(
            base_url=instance["url"],
            timeout=10,
            trust_env=False,
            headers={"Authorization": "Bearer " + instance["token"]},
        ) as client:
            assert client.get("/health").json()["database_revision"] == "0013"
            assert client.get("/api/events").json() == []
            assert client.get("/_desktop/status").json()["sync"]["enabled"] is False
            evidence["checks"].append(
                "new database initialized without reading activities before consent"
            )
            assert client.get("/_desktop/activitywatch").json()["currentwindow"] == 1
            for page in (
                "/setup",
                "/",
                "/review",
                "/unclassified",
                "/statistics",
                "/projects",
                "/games",
                "/game-preferences",
                "/library",
            ):
                assert client.get(page).status_code == 200, page
            for asset in (
                "appearance-init.js",
                "setup.js",
                "setup.css",
                "motion.js",
                "motion.css",
                "skins/minimal.css",
                "skins/terminal.css",
                "skins/sunny.css",
                "skins/editorial.css",
                "skins/arcade.css",
                "sunny-afternoon.png",
            ):
                assert client.get("/static/" + asset).status_code == 200, asset
            evidence["checks"].append("all pages and skins available from bundled resources")
            with httpx.Client(base_url=instance["url"], trust_env=False) as browser:
                response = browser.get(
                    "/_desktop/open", params={"token": instance["token"]}, follow_redirects=True
                )
                assert response.status_code == 200 and response.url.path == "/setup"
                assert browser.get("/_desktop/status").status_code == 200
            evidence["checks"].append("browser bootstrap exchanges token for local session")
            duplicate = subprocess.run(command, cwd=workspace, env=environment, timeout=30)
            assert duplicate.returncode == 0
            assert json.loads((profile / "runtime.json").read_text())["pid"] == process.pid
            evidence["checks"].append("duplicate launch reuses the same process")
            assert client.post("/_desktop/setup", json={"consent": True}).status_code == 200
            events = []
            for _ in range(100):
                events = client.get("/api/events").json()
                if events:
                    break
                time.sleep(0.1)
            assert len(events) == 1
            evidence["checks"].append(
                "real HTTP ActivityWatch adapter imports a synthetic activity"
            )
            identity = events[0]["id"]
            assert (
                client.put(
                    f"/api/events/{identity}/override",
                    json={"category": "work", "content": "Synthetic verification"},
                ).status_code
                == 200
            )
            assert client.post("/_desktop/sync", json={"enabled": False}).status_code == 200
            assert client.post("/_desktop/shutdown").status_code == 200
        assert process.wait(timeout=30) == 0
        assert not (profile / "runtime.json").exists()
        rules = profile / "config/rules.yaml"
        rules.write_text(
            rules.read_text(encoding="utf-8") + "\n# preserved user rule\n", encoding="utf-8"
        )
        rule_hash = hashlib.sha256(rules.read_bytes()).hexdigest()
        restart_command = list(command)
        port_index = restart_command.index("--port")
        del restart_command[port_index : port_index + 2]
        previous_port = json.loads((profile / "config/desktop.json").read_text())["web_port"]
        process = subprocess.Popen(restart_command, cwd=workspace, env=environment)
        instance = wait_instance(process, profile)
        assert urlsplit(instance["url"]).port == previous_port
        evidence["checks"].append("restart reuses the remembered port when available")
        with httpx.Client(
            base_url=instance["url"],
            timeout=10,
            trust_env=False,
            headers={"Authorization": "Bearer " + instance["token"]},
        ) as client:
            status = client.get("/_desktop/status").json()
            assert status["setup_completed"] and not status["sync"]["enabled"]
            assert client.get("/api/events").json()[0]["classification"]["origin"] == "manual"
            assert hashlib.sha256(rules.read_bytes()).hexdigest() == rule_hash
            assert client.post("/_desktop/shutdown").status_code == 200
        assert process.wait(timeout=30) == 0
        with sqlite3.connect(profile / "data/leisurelog.db") as database:
            assert database.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        evidence["checks"].append(
            "restart preserves manual correction, custom rules and stopped sync"
        )
        evidence["checks"].append("graceful exit leaves a verified SQLite database")
        evidence["result"] = "passed"
        (workspace / "result.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(evidence, ensure_ascii=False))
    finally:
        if process and process.poll() is None:
            subprocess.run(
                command[:1] + ["--data-dir", str(profile), "--stop"], timeout=10, env=environment
            )
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
        occupied.close()
        source.shutdown()
        source.server_close()


if __name__ == "__main__":
    main()
