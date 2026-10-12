from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ActivityContext:
    purpose: str = "unknown"
    project_id: str | None = None
    purpose_origin: str = "fallback"
    project_origin: str = "fallback"


@dataclass(frozen=True)
class Classification:
    category: str = "unknown"
    content: str | None = None
    tags: tuple[str, ...] = ()
    origin: str = "fallback"


@dataclass(frozen=True)
class ActivityEvent:
    id: str
    source: str
    stream: str
    device: str
    start_time: datetime
    end_time: datetime
    app: str
    title: str = ""
    url: str | None = None
    classification: Classification = field(default_factory=Classification)


@dataclass(frozen=True)
class SourceRecord:
    event: ActivityEvent
    source_event_id: str
    payload: dict[str, Any]
    metadata: dict[str, Any]
    # (start, end): whether the source cut this slice at the requested range's edge.
    cropped: tuple[bool, bool] = (False, False)


@dataclass(frozen=True)
class IdleEvent:
    id: str
    source: str
    stream: str
    device: str
    start_time: datetime
    end_time: datetime
    status: str


@dataclass(frozen=True)
class IdleSourceRecord:
    event: IdleEvent
    source_event_id: str
    payload: dict[str, Any]
    metadata: dict[str, Any]
    # (start, end): whether the source cut this slice at the requested range's edge.
    cropped: tuple[bool, bool] = (False, False)


@dataclass
class Session:
    id: str
    source: str
    stream: str
    device: str
    app: str
    title: str
    url: str | None
    start_time: datetime
    end_time: datetime
    active_seconds: float
    classification: Classification
    event_ids: list[str] = field(default_factory=list)
    recorded_seconds: float = 0
    afk_seconds: float = 0
    unverified_seconds: float = 0
    detected_afk_seconds: float = 0
    retained_afk_seconds: float = 0
    timing_policy: str = "afk"
    timing_origin: str = "default"
    context: ActivityContext = field(default_factory=ActivityContext)
