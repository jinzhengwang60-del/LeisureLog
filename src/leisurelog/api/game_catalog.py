"""Host controls for the persisted game catalog and its optional source provider."""

from fastapi import APIRouter, HTTPException, Request

from leisurelog.domain.game_catalog import GameCatalogUnavailable
from leisurelog.services.plugin_access import PluginAccessDenied
from leisurelog.services.plugin_runtime import PluginOperationError

router = APIRouter()


@router.get("/api/games/playnite")
def status(request: Request):
    return request.app.state.game_catalog.status()


@router.post("/api/games/playnite/import")
def import_games(request: Request):
    try:
        return request.app.state.game_catalog.refresh()
    except GameCatalogUnavailable as exc:
        raise HTTPException(422, str(exc)) from exc
    except (PluginOperationError, PluginAccessDenied) as exc:
        raise HTTPException(409, "游戏资料插件已停用、失效或暂时繁忙，请检查插件状态") from exc
