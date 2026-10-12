"""Independent purpose choices, reusable attribution rules, and project management."""

from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from leisurelog.analytics.projects import project_report
from leisurelog.analytics.query import BEIJING
from leisurelog.api.routes import Service
from leisurelog.api.schemas import EventSelection
from leisurelog.domain.activity_context import PURPOSES, Purpose
from leisurelog.repositories.activity_context import SQLiteContext
from leisurelog.services.activity_context import ActivityContextService

router = APIRouter()


class AttributionRequest(EventSelection):
    purpose: Purpose | None = None
    project_id: str | None = Field(default=None, min_length=1, max_length=100)
    remember_scope: Literal["app", "title", "domain", "url", "title_contains"] | None = None
    match_text: str | None = Field(default=None, min_length=2, max_length=300)

    @model_validator(mode="after")
    def explicit_choice(self):
        if not {"purpose", "project_id"} & self.model_fields_set:
            raise ValueError("Choose a purpose or project")
        return self


class ProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    color: str = Field(default="#6366f1", pattern=r"^#[0-9a-fA-F]{6}$")
    archived: bool = False

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Project name must not be blank")
        return value


def context_service(svc):
    return ActivityContextService(SQLiteContext(svc.repo.db), svc)


def handle_error(exc):
    if isinstance(exc, KeyError):
        raise HTTPException(404, "Project, rule or selected activity no longer exists") from exc
    raise HTTPException(422, str(exc)) from exc


@router.get("/projects", include_in_schema=False)
def projects_page():
    return FileResponse(Path(__file__).parent / "static/projects.html")


@router.get("/api/activity-context/options")
def options(svc: Service):
    return {"purposes": PURPOSES, "projects": SQLiteContext(svc.repo.db).projects()}


@router.put("/api/events/context")
def attribute(body: AttributionRequest, svc: Service):
    values = body.model_dump(include={"purpose", "project_id"}, exclude_unset=True)
    try:
        return context_service(svc).attribute(
            body.event_ids, values, body.remember_scope, body.match_text
        )
    except (KeyError, ValueError) as exc:
        handle_error(exc)


@router.delete("/api/events/context")
def restore(body: EventSelection, svc: Service):
    try:
        return context_service(svc).restore(body.event_ids)
    except (KeyError, ValueError) as exc:
        handle_error(exc)


@router.get("/api/activity-context/rules")
def context_rules(svc: Service):
    return [asdict(rule) for rule in SQLiteContext(svc.repo.db).context_rules()]


@router.delete("/api/activity-context/rules/{rule_id}")
def remove_rule(rule_id: str, svc: Service):
    try:
        return context_service(svc).remove_rule(rule_id)
    except (KeyError, ValueError) as exc:
        handle_error(exc)


@router.get("/api/projects")
def projects(
    svc: Service,
    start: date | None = Query(default=None, le=date(9998, 12, 31)),
    end: date | None = Query(default=None, le=date(9998, 12, 31)),
):
    today = datetime.now(BEIJING).date()
    try:
        return project_report(
            SQLiteContext(svc.repo.db), start or today.replace(day=1), end or today
        )
    except ValueError as exc:
        handle_error(exc)


@router.post("/api/projects", status_code=201)
def create_project(body: ProjectRequest, svc: Service):
    return SQLiteContext(svc.repo.db).save_project(None, body.model_dump())


@router.put("/api/projects/{project_id}")
def save_project(project_id: str, body: ProjectRequest, svc: Service):
    try:
        return SQLiteContext(svc.repo.db).save_project(project_id, body.model_dump())
    except KeyError as exc:
        handle_error(exc)


@router.get("/api/projects/{project_id}")
def project_details(
    project_id: str,
    svc: Service,
    start: date = Query(le=date(9998, 12, 31)),
    end: date = Query(le=date(9998, 12, 31)),
):
    try:
        return project_report(SQLiteContext(svc.repo.db), start, end, project_id)
    except (KeyError, ValueError) as exc:
        handle_error(exc)
