"""Enrich foreground window intervals; browser telemetry never adds time by itself."""

from bisect import bisect_left
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from leisurelog.domain.activity_context import ActivityContext
from leisurelog.domain.models import ActivityEvent


@dataclass(frozen=True)
class BrowserEvent:
    id: str
    source: str
    stream: str
    device: str
    start_time: datetime
    end_time: datetime
    browser_apps: tuple[str, ...]
    title: str
    url: str
    audible: bool = False


@dataclass(frozen=True)
class BrowserSourceRecord:
    event: BrowserEvent
    source_event_id: str
    payload: dict
    metadata: dict
    # (start, end): whether the source cut this slice at the requested range's edge.
    cropped: tuple[bool, bool] = (False, False)


@dataclass(frozen=True)
class ResolvedActivity(ActivityEvent):
    window_event_id: str = ""
    browser_event_id: str | None = None
    timing_policy: str = "afk"
    timing_origin: str = "default"
    audible: bool = False
    context: ActivityContext = field(default_factory=ActivityContext)


def matching_title(window: ActivityEvent, browser: BrowserEvent) -> bool:
    def normalized(value):
        return " ".join(value.replace("\u200b", "").replace("\u200e", "").split()).casefold()

    title, page = normalized(window.title), normalized(browser.title)
    if window.url and window.url == browser.url:
        return True
    return bool(page) and (
        title == page
        or any(title.startswith(page + suffix) for suffix in [" - ", " — ", " – ", " 和另外 "])
    )


def resolve_browser(windows: list[ActivityEvent], pages: list[BrowserEvent]):
    result = []
    grouped = {}
    for page in pages:
        for app in page.browser_apps:
            grouped.setdefault((page.source, page.device, app), []).append(page)
    indexes = {}
    for key, values in grouped.items():
        values.sort(key=lambda page: page.start_time)
        longest = max((page.end_time - page.start_time).total_seconds() for page in values)
        indexes[key] = (values, [page.start_time for page in values], longest)
    for window in windows:
        values, starts, longest = indexes.get(
            (window.source, window.device, window.app.casefold()), ([], [], 0)
        )
        first = bisect_left(starts, window.start_time - timedelta(seconds=longest))
        last = bisect_left(starts, window.end_time)
        candidates = [
            page
            for page in values[first:last]
            if window.device != "unknown"
            and window.source == page.source
            and window.device == page.device
            and window.app.casefold() in page.browser_apps
            and page.start_time < window.end_time
            and page.end_time > window.start_time
            and matching_title(window, page)
        ]
        if not candidates:
            result.append(ResolvedActivity(**window.__dict__, window_event_id=window.id))
            continue
        boundaries = sorted(
            {
                window.start_time,
                window.end_time,
                *[
                    boundary
                    for page in candidates
                    for boundary in (
                        max(window.start_time, page.start_time),
                        min(window.end_time, page.end_time),
                    )
                ],
            }
        )
        segments = []
        for start, end in zip(boundaries, boundaries[1:]):
            active = [
                page for page in candidates if page.start_time <= start and page.end_time >= end
            ]
            # Multiple identical reports can be collapsed; conflicting pages remain window-only.
            distinct = {(page.title, page.url) for page in active}
            chosen = min(active, key=lambda page: page.id) if len(distinct) == 1 else None
            key = chosen.id if chosen else None
            if segments and segments[-1][2] == key:
                segments[-1] = (segments[-1][0], end, key, chosen)
            else:
                segments.append((start, end, key, chosen))
        for start, end, key, page in segments:
            identity = f"leisurelog:resolved:{window.id}:{key}:{start.isoformat()}"
            event = replace(
                window,
                id=str(uuid5(NAMESPACE_URL, identity)),
                start_time=start,
                end_time=end,
                title=page.title if page else window.title,
                url=page.url if page else window.url,
            )
            result.append(
                ResolvedActivity(
                    **event.__dict__,
                    window_event_id=window.id,
                    browser_event_id=key,
                    audible=page.audible if page else False,
                )
            )
    return result
