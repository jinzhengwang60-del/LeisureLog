from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from leisurelog.adapters.playnite import PlayniteUnavailable
from leisurelog.analytics.games import game_detail, game_listing
from leisurelog.api.routes import Service
from leisurelog.repositories.game_statistics import SQLiteGameStatistics
from leisurelog.repositories.games import SQLiteGameCatalog
from leisurelog.services.games import GameImportService

router = APIRouter()


@router.get("/games", include_in_schema=False)
def game_page():
    return FileResponse(Path(__file__).parent / "static/game-statistics.html")


@router.get("/api/game-statistics")
def statistics(
    svc: Service,
    query: str = Query(default="", max_length=300),
    scope: Literal["tracked", "recorded", "all"] = "tracked",
    sort: Literal["time", "recent"] = "time",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return game_listing(SQLiteGameStatistics(svc.repo.db), query, scope, sort, limit, offset)


@router.get("/api/game-statistics/{key:path}")
def statistics_detail(
    key: str,
    svc: Service,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        return game_detail(SQLiteGameStatistics(svc.repo.db), key, limit, offset)
    except KeyError as exc:
        raise HTTPException(404, "游戏条目不存在，请刷新") from exc


@router.get("/api/games/playnite")
def status(request: Request, svc: Service):
    return {
        "export_path": str(request.app.state.playnite.path.resolve()),
        **SQLiteGameCatalog(svc.repo.db).status(),
    }


@router.post("/api/games/playnite/import")
def import_games(request: Request, svc: Service):
    try:
        payload, games = request.app.state.playnite.fetch()
    except PlayniteUnavailable as exc:
        raise HTTPException(422, str(exc)) from exc
    return GameImportService(SQLiteGameCatalog(svc.repo.db), svc).import_catalog(payload, games)
