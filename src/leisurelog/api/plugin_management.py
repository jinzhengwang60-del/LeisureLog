"""Always-available host page for registered local feature controls."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/plugins", include_in_schema=False)
def management_page():
    return FileResponse(
        Path(__file__).parent / "static/plugins.html",
        headers={"Cache-Control": "no-store"},
    )
