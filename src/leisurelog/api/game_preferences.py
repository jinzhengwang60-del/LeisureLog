from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints

from leisurelog.analytics.game_preferences import preferences
from leisurelog.api.routes import Service
from leisurelog.domain.game_types import type_options
from leisurelog.repositories.game_preferences import SQLiteGamePreferences
from leisurelog.services.game_types import GameTypeService

router = APIRouter()
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class TypeChoice(BaseModel):
    primary: Annotated[str, StringConstraints(max_length=50)]
    tags: list[Tag] = Field(default_factory=list, max_length=50)
    model_config = {"extra": "forbid"}


@router.get("/game-preferences", include_in_schema=False)
def page():
    return FileResponse(Path(__file__).parent / "static/game-preferences.html")


@router.get("/api/game-types")
def options():
    return {"types": type_options()}


@router.get("/api/game-preferences")
def report(
    svc: Service,
    start: date = Query(le=date(9998, 12, 31)),
    end: date = Query(le=date(9998, 12, 31)),
):
    try:
        return preferences(SQLiteGamePreferences(svc.repo.db), start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put("/api/game-types/{key:path}")
def save(key: str, body: TypeChoice, svc: Service):
    store = SQLiteGamePreferences(svc.repo.db)
    try:
        GameTypeService(store).save(key, body.primary, body.tags)
        return store.detail(key)
    except KeyError as exc:
        raise HTTPException(404, "游戏条目不存在，请刷新") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/api/game-types/{key:path}")
def reset(key: str, svc: Service):
    store = SQLiteGamePreferences(svc.repo.db)
    try:
        GameTypeService(store).reset(key)
        return store.detail(key)
    except KeyError as exc:
        raise HTTPException(404, "游戏条目不存在，请刷新") from exc
