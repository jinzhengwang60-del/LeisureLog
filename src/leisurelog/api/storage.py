import logging
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from leisurelog.domain.storage import BackupBusy

router = APIRouter(prefix="/api/storage")
logger = logging.getLogger(__name__)


@router.get("")
def overview(request: Request):
    state = request.app.state
    return {
        **state.storage.overview(),
        "automatic_backup": {
            **state.backup_scheduler.snapshot(),
            "every_days": state.settings.auto_backup_days,
            "keep": state.settings.auto_backup_keep,
        },
    }


@router.post("/backups", status_code=201)
def create_backup(request: Request):
    try:
        return request.app.state.storage.backup()
    except BackupBusy as exc:
        raise HTTPException(409, "Backup already running") from exc
    except (OSError, ValueError, sqlite3.Error) as exc:
        logger.exception("Local backup failed")
        raise HTTPException(503, "Backup failed; check storage space and permissions") from exc


@router.get("/backups/{name}/download")
def download_backup(name: str, request: Request):
    try:
        path = request.app.state.storage.store.download_path(name)
    except KeyError as exc:
        raise HTTPException(404, "Backup not found") from exc
    return FileResponse(path, filename=path.name, media_type="application/vnd.sqlite3")


@router.get("/backups/{name}/archive")
def download_archive(name: str, request: Request):
    try:
        path = request.app.state.storage.store.download_path(name).with_suffix(".zip")
        if not path.is_file() or path.is_symlink():
            raise KeyError(name)
    except KeyError as exc:
        raise HTTPException(404, "Backup not found") from exc
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/compact")
def compact(request: Request):
    try:
        return request.app.state.storage.compact()
    except BackupBusy as exc:
        raise HTTPException(409, "Storage maintenance already running") from exc
    except (OSError, ValueError, sqlite3.Error) as exc:
        logger.exception("Local compaction failed")
        raise HTTPException(503, "Compaction failed; no unbacked revisions deleted") from exc
