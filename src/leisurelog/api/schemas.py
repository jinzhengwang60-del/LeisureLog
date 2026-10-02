from datetime import timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: AwareDatetime
    end: AwareDatetime
    buckets: list[str] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def valid_window(self):
        if not timedelta(0) < self.end - self.start <= timedelta(days=7):
            raise ValueError("Sync window must be positive and at most 7 days")
        if self.buckets is not None and (
            not self.buckets or len(set(self.buckets)) != len(self.buckets)
        ):
            raise ValueError("Buckets must be nonempty and unique")
        return self


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(min_length=1, max_length=100)
    content: str | None = Field(default=None, max_length=300)
    tags: list[str] = Field(default_factory=list, max_length=30)


class EventSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_ids: list[str] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("Event IDs must be unique")
        if any(not key or len(key) > 100 for key in self.event_ids):
            raise ValueError("Invalid event ID")
        return self


class BatchOverrideRequest(OverrideRequest, EventSelection):
    remember_scope: Literal["app", "title", "domain", "url"] | None = None


class TimingRequest(EventSelection):
    policy: Literal["afk", "foreground", "audible"] | None = None
