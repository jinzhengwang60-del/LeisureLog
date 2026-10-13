from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timezone-aware datetime required")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Base(DeclarativeBase):
    pass


class GameSnapshotRow(Base):
    __tablename__ = "game_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    digest: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime)


class GameCatalogRow(Base):
    __tablename__ = "game_catalog"
    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    installed: Mapped[bool]
    directory: Mapped[str]
    tags: Mapped[list] = mapped_column(JSON)
    matches: Mapped[list] = mapped_column(JSON)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("game_snapshots.id"))


class GameTypeOverrideRow(Base):
    __tablename__ = "game_type_overrides"
    # Stable statistics key, deliberately independent of replaceable catalog rows.
    game_key: Mapped[str] = mapped_column(String, primary_key=True)
    primary_type: Mapped[str]
    tags: Mapped[list] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ContentItemRow(Base):
    __tablename__ = "content_items"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    category: Mapped[str]
    notes: Mapped[str] = mapped_column(String, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ContentAliasRow(Base):
    __tablename__ = "content_aliases"
    __table_args__ = (UniqueConstraint("app", "category", "name"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("content_items.id"), index=True)
    app: Mapped[str]
    category: Mapped[str]
    name: Mapped[str]


class LearnedRuleRow(Base):
    __tablename__ = "learned_rules"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str]
    app: Mapped[str]
    scope: Mapped[str]
    value: Mapped[str]
    classification: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class SyncCheckpointRow(Base):
    __tablename__ = "sync_checkpoints"
    source: Mapped[str] = mapped_column(String, primary_key=True)
    last_success_end: Mapped[datetime] = mapped_column(UTCDateTime)


class RawEventRow(Base):
    __tablename__ = "raw_events"
    __table_args__ = (UniqueConstraint("event_id", "payload_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str]
    stream: Mapped[str]
    source_event_id: Mapped[str]
    payload_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    source_metadata: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc)
    )


class ActivityEventRow(Base):
    __tablename__ = "activity_events"
    __table_args__ = (
        Index(
            "ix_activity_events_processing", "source", "device", "stream", "end_time", "start_time"
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    raw_event_id: Mapped[int] = mapped_column(ForeignKey("raw_events.id"))
    source: Mapped[str]
    stream: Mapped[str]
    device: Mapped[str]
    start_time: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime)
    app: Mapped[str]
    title: Mapped[str]
    url: Mapped[str | None]
    classification: Mapped[dict] = mapped_column(JSON)


class ManualOverrideRow(Base):
    __tablename__ = "manual_overrides"
    event_id: Mapped[str] = mapped_column(ForeignKey("activity_events.id"), primary_key=True)
    classification: Mapped[dict] = mapped_column(JSON)


class IdleEventRow(Base):
    __tablename__ = "idle_events"
    __table_args__ = (
        Index("ix_idle_events_processing", "source", "device", "end_time", "start_time"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    raw_event_id: Mapped[int] = mapped_column(ForeignKey("raw_events.id"))
    source: Mapped[str]
    stream: Mapped[str]
    device: Mapped[str]
    start_time: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str]


class SessionRow(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_processing", "source", "device", "stream", "end_time", "start_time"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str]
    stream: Mapped[str]
    device: Mapped[str]
    app: Mapped[str]
    title: Mapped[str]
    url: Mapped[str | None]
    start_time: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime)
    active_seconds: Mapped[float] = mapped_column(Float)
    recorded_seconds: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    afk_seconds: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    unverified_seconds: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    detected_afk_seconds: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    retained_afk_seconds: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    timing_policy: Mapped[str] = mapped_column(String, default="afk", server_default="afk")
    timing_origin: Mapped[str] = mapped_column(String, default="default", server_default="default")
    classification: Mapped[dict] = mapped_column(JSON)
    context: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class SessionEventRow(Base):
    __tablename__ = "session_events"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("resolved_events.id"), primary_key=True)


class DailyActivityRow(Base):
    __tablename__ = "daily_activity"
    __table_args__ = (
        Index("ix_daily_activity_content", "app", "category", "content"),
        Index("ix_daily_activity_purpose_day", "purpose", "day"),
        Index("ix_daily_activity_project_day", "project_id", "day"),
    )
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    app: Mapped[str]
    category: Mapped[str]
    content: Mapped[str | None]
    purpose: Mapped[str] = mapped_column(String, default="unknown", server_default="unknown")
    project_id: Mapped[str | None] = mapped_column(String)
    recorded_seconds: Mapped[float] = mapped_column(Float)
    active_seconds: Mapped[float] = mapped_column(Float)
    afk_seconds: Mapped[float] = mapped_column(Float)
    unverified_seconds: Mapped[float] = mapped_column(Float)
    detected_afk_seconds: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    retained_afk_seconds: Mapped[float] = mapped_column(Float, default=0, server_default="0")


class BrowserEventRow(Base):
    __tablename__ = "browser_events"
    __table_args__ = (
        Index("ix_browser_events_processing", "source", "device", "end_time", "start_time"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    raw_event_id: Mapped[int] = mapped_column(ForeignKey("raw_events.id"))
    source: Mapped[str]
    stream: Mapped[str]
    device: Mapped[str]
    start_time: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime)
    browser_apps: Mapped[list] = mapped_column(JSON)
    title: Mapped[str]
    url: Mapped[str]
    audible: Mapped[bool] = mapped_column(Boolean)


class ResolvedEventRow(Base):
    __tablename__ = "resolved_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    window_event_id: Mapped[str] = mapped_column(ForeignKey("activity_events.id"), index=True)
    browser_event_id: Mapped[str | None] = mapped_column(ForeignKey("browser_events.id"))
    source: Mapped[str]
    stream: Mapped[str]
    device: Mapped[str]
    start_time: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime)
    app: Mapped[str]
    title: Mapped[str]
    url: Mapped[str | None]
    classification: Mapped[dict] = mapped_column(JSON)
    timing_policy: Mapped[str] = mapped_column(String, default="afk", server_default="afk")
    timing_origin: Mapped[str] = mapped_column(String, default="default", server_default="default")
    audible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    context: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class ActivityProjectRow(Base):
    __tablename__ = "activity_projects"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    description: Mapped[str] = mapped_column(String, default="", server_default="")
    color: Mapped[str] = mapped_column(String, default="#6366f1", server_default="#6366f1")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    goal_seconds: Mapped[float | None] = mapped_column(Float)


class ContextOverrideRow(Base):
    __tablename__ = "context_overrides"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    window_event_id: Mapped[str] = mapped_column(ForeignKey("activity_events.id"), index=True)
    assignments: Mapped[dict] = mapped_column(JSON)


class ContextRuleRow(Base):
    __tablename__ = "context_rules"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str]
    app: Mapped[str]
    scope: Mapped[str]
    value: Mapped[str]
    assignments: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ContextChangeRow(Base):
    __tablename__ = "context_changes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    action: Mapped[str]
    event_count: Mapped[int]
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    undone_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class TimingOverrideRow(Base):
    __tablename__ = "timing_overrides"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    window_event_id: Mapped[str] = mapped_column(ForeignKey("activity_events.id"))
    policy: Mapped[str]


class SegmentOverrideRow(Base):
    __tablename__ = "segment_overrides"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    window_event_id: Mapped[str] = mapped_column(ForeignKey("activity_events.id"))
    classification: Mapped[dict] = mapped_column(JSON)
