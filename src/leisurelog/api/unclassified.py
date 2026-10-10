from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from leisurelog.analytics.unclassified import unclassified_report
from leisurelog.api.routes import Service
from leisurelog.domain.models import Classification

router = APIRouter()


class AppRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=100)
    app: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=100)
    content: str | None = Field(default=None, max_length=300)

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value.strip() in {"", "unknown"}:
            raise ValueError("Choose a category other than unknown")
        return value.strip()


@router.get("/unclassified", include_in_schema=False)
def page():
    return FileResponse(Path(__file__).parent / "static" / "unclassified.html")


@router.get("/api/unclassified")
def read_unclassified(svc: Service):
    return unclassified_report(svc.repo)


@router.post("/api/classification/app-rules")
def remember_app(body: AppRuleRequest, svc: Service):
    content = (body.content or "").strip() or None
    try:
        result = svc.remember_app(
            body.source,
            body.app,
            Classification(category=body.category, content=content, origin="manual"),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "No activity recorded for this app") from exc
    return {**result, **unclassified_report(svc.repo)}


class AppRuleBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[AppRuleRequest] = Field(min_length=1, max_length=200)


@router.post("/api/classification/app-rules/batch")
def remember_apps(body: AppRuleBatch, svc: Service):
    """Save many app rules (e.g. accepted suggestions) and rebuild once; all or nothing."""
    items = [
        (
            rule.source,
            rule.app,
            Classification(
                category=rule.category,
                content=(rule.content or "").strip() or None,
                origin="manual",
            ),
        )
        for rule in body.rules
    ]
    try:
        result = svc.remember_apps(items)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    return {**result, **unclassified_report(svc.repo)}
