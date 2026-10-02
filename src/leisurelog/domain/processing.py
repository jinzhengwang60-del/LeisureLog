"""Affected intervals, independent of storage or source implementations."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta


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
