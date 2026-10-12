from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from leisurelog.analytics.activity_review import activity_review
from leisurelog.analytics.query import BEIJING
from leisurelog.analytics.review import review
from leisurelog.api.routes import Service
from leisurelog.repositories.activity_context import SQLiteContext

router = APIRouter()


@router.get("/review", include_in_schema=False)
def page():
    return FileResponse(Path(__file__).parent / "static" / "review.html")


@router.get("/api/review")
def read_review(svc: Service, day: date | None = Query(default=None, le=date(9998, 12, 31))):
    """The Monday–Sunday week containing ``day`` (default: this week)."""
    today = datetime.now(BEIJING).date()
    return {
        **review(svc.repo, day or today, today),
        **activity_review(SQLiteContext(svc.repo.db), day or today, today),
    }
