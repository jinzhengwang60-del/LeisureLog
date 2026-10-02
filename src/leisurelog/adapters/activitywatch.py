import json
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import httpx

from leisurelog.adapters.activitywatch_browser import ActivityWatchBrowserAdapter
from leisurelog.domain.browser import BrowserSourceRecord
from leisurelog.domain.models import ActivityEvent, IdleEvent, IdleSourceRecord, SourceRecord


class SourceUnavailable(Exception):
    pass


class ActivityWatchAdapter:
    """Read foreground windows and matching device AFK states without changing AW."""

    def __init__(self, client: httpx.Client, device_bindings=None):
        self.client = client
        self.browser = ActivityWatchBrowserAdapter(client, device_bindings)

    def _get(self, path: str, **params):
        response = self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def fetch(
        self, start: datetime, end: datetime, buckets: list[str] | None
    ) -> list[SourceRecord | IdleSourceRecord | BrowserSourceRecord]:
        try:
            available = self._get("/api/0/buckets/")
            selected = (
                buckets
                if buckets is not None
                else [
                    key for key, value in available.items() if value.get("type") == "currentwindow"
                ]
            )
            result = []
            for bucket in selected:
                if bucket not in available or available[bucket].get("type") != "currentwindow":
                    raise ValueError("Bucket must exist and have type currentwindow")
            devices = {available[key].get("hostname") for key in selected}
            selected = list(selected) + [
                key
                for key, value in available.items()
                if value.get("type") == "afkstatus"
                and value.get("hostname") in devices
                and value.get("hostname") not in {None, "unknown", ""}
            ]
            for bucket in selected:
                metadata = available.get(bucket)
                # Read all events in the bounded window, avoiding silent count truncation.
                payloads = self._get(
                    f"/api/0/buckets/{quote(bucket, safe='')}/events",
                    start=start.isoformat(),
                    end=end.isoformat(),
                    limit=-1,
                )
                for payload in payloads:
                    begin = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
                    if begin.tzinfo is None:
                        raise ValueError("Source timestamp must include timezone")
                    begin = begin.astimezone(timezone.utc)
                    duration = float(payload["duration"])
                    if not math.isfinite(duration) or duration < 0:
                        raise ValueError("Invalid source duration")
                    finish = begin + timedelta(seconds=duration)
                    if begin >= end or finish < start:
                        continue
                    source_id = str(payload["id"])
                    identity = json.dumps(["activitywatch", bucket, source_id])
                    data = payload["data"]
                    if metadata["type"] == "afkstatus":
                        if data.get("status") not in {"afk", "not-afk"}:
                            raise ValueError("Invalid AFK state")
                        result.append(
                            IdleSourceRecord(
                                event=IdleEvent(
                                    id=str(uuid5(NAMESPACE_URL, identity)),
                                    source="activitywatch",
                                    stream=bucket,
                                    device=metadata["hostname"],
                                    start_time=begin,
                                    end_time=finish,
                                    status=data["status"],
                                ),
                                source_event_id=source_id,
                                payload=payload,
                                metadata=metadata,
                            )
                        )
                        continue
                    result.append(
                        SourceRecord(
                            event=ActivityEvent(
                                id=str(uuid5(NAMESPACE_URL, identity)),
                                source="activitywatch",
                                stream=bucket,
                                device=metadata.get("hostname") or "unknown",
                                start_time=begin,
                                end_time=finish,
                                app=str(data.get("app", "")),
                                title=str(data.get("title", "")),
                                url=data.get("url"),
                            ),
                            source_event_id=source_id,
                            payload=payload,
                            metadata=metadata,
                        )
                    )
            result.extend(
                self.browser.fetch(
                    available,
                    start,
                    end,
                    {
                        m.get("hostname")
                        for m in available.values()
                        if m.get("type") == "currentwindow"
                    }
                    - {None, "", "unknown"},
                )
            )
            return result
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            OverflowError,
        ) as exc:
            raise SourceUnavailable("ActivityWatch unavailable or returned invalid data") from exc
