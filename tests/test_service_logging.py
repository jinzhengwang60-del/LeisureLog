"""The script deployment uses bounded logging, independently of the desktop launcher."""

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def test_script_service_logs_rotate_in_utf8(tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config/logging.json").read_text(encoding="utf-8"))
    spec = config["handlers"]["service"]
    assert spec["class"] == "logging.handlers.RotatingFileHandler"
    assert spec["maxBytes"] == 2_000_000 and spec["backupCount"] == 3
    assert config["loggers"]["uvicorn"]["propagate"] is False
    handler = RotatingFileHandler(
        tmp_path / "server.log", maxBytes=600, backupCount=spec["backupCount"],
        encoding=spec["encoding"],
    )
    logger = logging.getLogger("leisurelog-test-rotation")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        for number in range(100):
            logger.info("记录与恢复 %s %s", number, "x" * 150)
    finally:
        logger.removeHandler(handler)
        handler.close()
    logs = list(tmp_path.glob("server.log*"))
    assert len(logs) == 4 and sum(path.stat().st_size for path in logs) <= 2400
    assert "记录与恢复 99" in (tmp_path / "server.log").read_text(encoding="utf-8")
    assert "--log-config', 'config/logging.json'" in (
        root / "scripts/leisurelog.ps1"
    ).read_text(encoding="utf-8-sig")
