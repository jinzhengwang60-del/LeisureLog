from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text

from leisurelog.analytics.library import catalog, content_detail, duplicates
from leisurelog.repositories.library import SQLiteLibrary
from leisurelog.services.library import LibraryService

router = APIRouter()
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class EditItem(BaseModel):
    name: Name
    notes: str = ""

    model_config = {"str_max_length": 2000}


class AddAlias(BaseModel):
    app: Name
    name: Name


class MergeItem(BaseModel):
    source_id: Name


class MergeGroup(BaseModel):
    target_id: Name
    source_ids: list[Name] = Field(min_length=1, max_length=50)


class MergeGroups(BaseModel):
    groups: list[MergeGroup] = Field(min_length=1, max_length=200)


def library_service(request: Request):
    with request.app.state.sessions() as db:
        db.execute(text("BEGIN" if request.method == "GET" else "BEGIN IMMEDIATE"))
        try:
            yield LibraryService(SQLiteLibrary(db))
            db.commit()
        except Exception:
            db.rollback()
            raise


Library = Annotated[LibraryService, Depends(library_service)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def change(action):
    try:
        return action()
    except KeyError as exc:
        raise HTTPException(404, "内容或名称不存在，请刷新") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/library", include_in_schema=False)
def page():
    return FileResponse(Path(__file__).parent / "static/library.html")


COVER_LIMIT = 15_000_000


@router.get("/api/library")
def listing(
    request: Request,
    svc: Library,
    query: str = Query(default="", max_length=300),
    category: str = Query(default="", max_length=100),
    sort: Literal["recent", "time"] = "recent",
    limit: PageLimit = 50,
    offset: Offset = 0,
):
    result = catalog(svc.store, query, category, sort, limit, offset)
    index = request.app.state.playnite.covers()
    for item in result["items"]:
        game = item["category"] == "game"
        hit = index.cover_for(item["name"], item.get("apps") or []) if game else None
        item["cover"] = f"/api/library/cover?game={hit[0]}" if hit else None
    return result


@router.get("/api/library/duplicates")
def read_duplicates(svc: Library):
    """Groups of items that look like the same thing recorded from different programs."""
    return {"groups": duplicates(svc.store)}


@router.post("/api/library/duplicates/merge")
def merge_duplicates(body: MergeGroups, svc: Library):
    """Merge the given groups in one transaction: all of them or none."""
    merged = change(
        lambda: svc.merge_many([(group.target_id, group.source_ids) for group in body.groups])
    )
    return {"merged": merged, "groups": duplicates(svc.store)}


@router.get("/api/library/cover")
def cover(request: Request, game: Annotated[str, StringConstraints(max_length=64)]):
    """A game's cover image from the local Playnite library, by Playnite game ID."""
    path = request.app.state.playnite.covers().covers.get(game.strip().casefold())
    try:
        if path is None or not path.is_file() or path.stat().st_size > COVER_LIMIT:
            raise HTTPException(404, "No cover for this name")
    except OSError as exc:
        raise HTTPException(404, "No cover for this name") from exc
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})


@router.get("/api/library/{item_id}")
def detail(item_id: str, svc: Library, limit: PageLimit = 30, offset: Offset = 0):
    return change(lambda: content_detail(svc.store, item_id, limit, offset))


@router.patch("/api/library/{item_id}")
def edit(item_id: str, body: EditItem, svc: Library):
    change(lambda: svc.rename(item_id, body.name, body.notes))
    return content_detail(svc.store, item_id, 30, 0)


@router.post("/api/library/{item_id}/aliases")
def add_alias(item_id: str, body: AddAlias, svc: Library):
    change(lambda: svc.add_alias(item_id, body.app, body.name))
    return content_detail(svc.store, item_id, 30, 0)


@router.post("/api/library/{item_id}/merge")
def merge(item_id: str, body: MergeItem, svc: Library):
    change(lambda: svc.merge(item_id, body.source_id))
    return content_detail(svc.store, item_id, 30, 0)


@router.post("/api/library/{item_id}/aliases/{alias_id}/split")
def split(item_id: str, alias_id: str, svc: Library):
    new_id = change(lambda: svc.split(item_id, alias_id))
    return content_detail(svc.store, new_id, 30, 0)
