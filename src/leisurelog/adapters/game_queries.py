"""HTTP-independent validation of the fixed game projection queries."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator


class GameListQuery(BaseModel):
    query: str = Field(default="", max_length=300)
    scope: Literal["tracked", "recorded", "all"] = "tracked"
    sort: Literal["time", "recent"] = "time"
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class GameDetailQuery(BaseModel):
    limit: int = Field(default=30, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class GameRangeQuery(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def range(self):
        if self.end > date(9998, 12, 31) or self.start > date(9998, 12, 31):
            raise ValueError("日期不能超过 9998 年")
        if self.end < self.start or (self.end - self.start).days >= 3660:
            raise ValueError("日期需按先后排列，范围最多 3660 天")
        return self


class EmptyQuery(BaseModel):
    pass


Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class GameTypeChoice(BaseModel):
    primary: str = Field(max_length=50)
    tags: list[Tag] = Field(default_factory=list, max_length=50)
    model_config = {"extra": "forbid"}
