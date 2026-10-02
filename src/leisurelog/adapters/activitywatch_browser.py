import json
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit
from uuid import NAMESPACE_URL, uuid5

from leisurelog.domain.browser import BrowserEvent, BrowserSourceRecord


class ActivityWatchBrowserAdapter:
    def __init__(self, client, device_bindings=None):
        self.client = client
        self.device_bindings = device_bindings or {}

    def fetch(self, available, start, end, devices):
        result = []
        for bucket, metadata in available.items():
            if metadata.get("type") != "web.tab.current":
                continue
            device = self.device_bindings.get(bucket) or metadata.get("hostname") or "unknown"
            if device == "unknown" and len(devices) == 1:
                device = next(iter(devices))
            name = (bucket + " " + metadata.get("client", "")).casefold()
            apps = (
                ("msedge.exe",)
                if "edge" in name
                else (
                    ("chrome.exe", "msedge.exe")
                    if "chrome" in name or "chromium" in name
                    else ("firefox.exe",)
                    if "firefox" in name
                    else ()
                )
            )
            response = self.client.get(
                f"/api/0/buckets/{quote(bucket, safe='')}/events",
                params={"start": start.isoformat(), "end": end.isoformat(), "limit": -1},
            )
            response.raise_for_status()
            for payload in response.json():
                data = payload["data"]
                if not isinstance(data.get("incognito", False), bool):
                    raise ValueError("Invalid incognito flag")
                if data.get("incognito", False):
                    continue
                url, title = data.get("url", ""), data.get("title", "")
                if not isinstance(url, str) or not isinstance(title, str):
                    raise ValueError("Invalid browser text")
                parsed = urlsplit(url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    continue
                if not isinstance(data.get("audible", False), bool):
                    raise ValueError("Invalid audible flag")
                begin = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
                if begin.tzinfo is None:
                    raise ValueError("Source timestamp must include timezone")
                begin = begin.astimezone(timezone.utc)
                duration = float(payload["duration"])
                if not math.isfinite(duration) or duration < 0:
                    raise ValueError("Invalid browser duration")
                finish = begin + timedelta(seconds=duration)
                if begin >= end or finish <= start:
                    continue
                source_id = str(payload["id"])
                identity = json.dumps(["activitywatch", bucket, source_id])
                result.append(
                    BrowserSourceRecord(
                        BrowserEvent(
                            str(uuid5(NAMESPACE_URL, identity)),
                            "activitywatch",
                            bucket,
                            device,
                            begin,
                            finish,
                            apps,
                            title,
                            url,
                            data.get("audible", False),
                        ),
                        source_id,
                        payload,
                        {**metadata, "leisurelog_bound_device": device},
                    )
                )
        return result
