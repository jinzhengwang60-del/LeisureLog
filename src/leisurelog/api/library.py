from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy import text

from leisurelog.analytics.library import catalog, content_detail
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


@router.get("/api/library")
def listing(
    svc: Library,
    query: str = Query(default="", max_length=300),
    category: str = Query(default="", max_length=100),
    sort: Literal["recent", "time"] = "recent",
    limit: PageLimit = 50,
    offset: Offset = 0,
):
    return catalog(svc.store, query, category, sort, limit, offset)


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
