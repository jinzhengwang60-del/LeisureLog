"""Affected intervals, independent of storage or source implementations."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta


def context_neighborhood(memberships, changed_event_ids):
    """Whole old Sessions plus one adjacent Session on each side per stream.

    A context edit preserves event order, intervals, classification and timing.
    Disjoint neighbourhoods stay separate: omitted Sessions remain merge barriers.
    Overlapping events may propagate a merge beyond a neighbour's former end;
    in that case rebuild the stream from its existing resolved facts.
    Memberships must follow the same (start, end, id) event order as sessionization.
    """
    streams, seeds, ends, overlaps = {}, {}, {}, set()
    for source, device, stream, session_id, event_id, start, end in memberships:
        key = source, device, stream
        if key in ends and start < ends[key]:
            overlaps.add(key)
        ends[key] = max(ends.get(key, end), end)
        ordered = streams.setdefault(key, [])
        if not ordered or ordered[-1] != session_id:
            ordered.append(session_id)
        if event_id in changed_event_ids:
            seeds.setdefault(key, set()).add(len(ordered) - 1)
    batches = []
    for key, indices in seeds.items():
        ordered = streams[key]
        if key in overlaps:
            batches.append(set(ordered))
            continue
        chosen = sorted(
            {
                index + offset
                for index in indices
                for offset in (-1, 0, 1)
                if 0 <= index + offset < len(ordered)
            }
        )
        previous = None
        for index in chosen:
            if previous is None or index != previous + 1:
                batches.append(set())
            batches[-1].add(ordered[index])
            previous = index
    return batches


@dataclass(frozen=True)
class ProcessingRange:
    source: str
    device: str
    stream: str | None
    start: datetime
    end: datetime


def coalesce(ranges: list[ProcessingRange], gap_seconds: float = 0) -> list[ProcessingRange]:
    result: list[ProcessingRange] = []
    gap = timedelta(seconds=gap_seconds)
    for value in sorted(ranges, key=lambda r: (r.source, r.device, r.stream or "", r.start)):
        if result:
            last = result[-1]
            if (last.source, last.device, last.stream) == (
                value.source,
                value.device,
                value.stream,
            ) and value.start <= last.end + gap:
                result[-1] = replace(last, end=max(last.end, value.end))
                continue
        result.append(value)
    return result
