from collections import defaultdict
from uuid import NAMESPACE_URL, uuid5

from leisurelog.domain.models import ActivityEvent, Session


def merge_sessions(events: list[ActivityEvent], gap_seconds: float) -> list[Session]:
    """Merge adjacent matching activities per source stream; gaps are not active time."""
    streams = defaultdict(list)
    for event in events:
        if event.end_time > event.start_time:
            streams[(event.source, event.device, event.stream)].append(event)
    result = []
    for stream_events in streams.values():
        current = None
        previous_key = None
        for event in sorted(stream_events, key=lambda e: (e.start_time, e.end_time, e.id)):
            key = (
                event.app.casefold(),
                event.title,
                event.url,
                event.classification,
                getattr(event, "timing_policy", "afk"),
                getattr(event, "timing_origin", "default"),
                getattr(event, "timing_policy", "afk") == "audible"
                and getattr(event, "audible", False),
            )
            gap = (event.start_time - current.end_time).total_seconds() if current else None
            if current and key == previous_key and gap <= gap_seconds:
                # Count the union of intervals, excluding bridge gaps and duplicate overlap.
                current.active_seconds += max(
                    0, (event.end_time - max(event.start_time, current.end_time)).total_seconds()
                )
                current.end_time = max(current.end_time, event.end_time)
                current.event_ids.append(event.id)
            else:
                current = Session(
                    id=str(uuid5(NAMESPACE_URL, "leisurelog:session:" + event.id)),
                    source=event.source,
                    stream=event.stream,
                    device=event.device,
                    app=event.app,
                    title=event.title,
                    url=event.url,
                    start_time=event.start_time,
                    end_time=event.end_time,
                    active_seconds=(event.end_time - event.start_time).total_seconds(),
                    classification=event.classification,
                    event_ids=[event.id],
                    timing_policy=getattr(event, "timing_policy", "afk"),
                    timing_origin=getattr(event, "timing_origin", "default"),
                )
                result.append(current)
            previous_key = key
    return sorted(result, key=lambda s: (s.start_time, s.id))
