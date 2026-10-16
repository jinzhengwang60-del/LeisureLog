"""Local control for registered official definitions; no arbitrary imports or installs."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from leisurelog.domain.plugins import PluginPermission, PluginResolutionError
from leisurelog.services.plugin_runtime import PluginOperationError

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class EnablePlugin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grants: dict[str, list[PluginPermission]] = Field(default_factory=dict)
    expected_revision: int | None = Field(default=None, ge=0, strict=True)


class DisablePlugin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cascade: bool = Field(default=False, strict=True)
    expected_revision: int | None = Field(default=None, ge=0, strict=True)


def _run(operation):
    try:
        return operation()
    except (PluginOperationError, PluginResolutionError) as error:
        status = 404 if error.issue.code == "missing_plugin" else 409
        if error.issue.code == "configuration_write_failed":
            status = 503
        raise HTTPException(
            status, {"code": error.issue.code, "message": error.issue.message}
        ) from None


@router.get("")
def plugin_status(request: Request):
    return request.app.state.plugins.snapshot()


@router.get("/{plugin_id}/plan")
def operation_plan(
    plugin_id: str,
    request: Request,
    operation: Literal["enable", "disable", "revoke"] = "enable",
    permission: PluginPermission | None = None,
    expected_revision: int | None = Query(default=None, ge=0),
):
    return _run(
        lambda: request.app.state.plugins.preview(
            plugin_id,
            operation,
            permission=permission,
            expected_revision=expected_revision,
        )
    )


@router.post("/{plugin_id}/enable")
def enable(plugin_id: str, body: EnablePlugin, request: Request):
    return _run(
        lambda: request.app.state.plugins.enable(
            plugin_id,
            body.grants,
            expected_revision=body.expected_revision,
        )
    )


@router.post("/{plugin_id}/disable")
def disable(plugin_id: str, body: DisablePlugin, request: Request):
    return _run(
        lambda: request.app.state.plugins.disable(
            plugin_id,
            cascade=body.cascade,
            expected_revision=body.expected_revision,
        )
    )


@router.delete("/{plugin_id}/permissions/{permission}")
def revoke(
    plugin_id: str,
    permission: PluginPermission,
    request: Request,
    expected_revision: int | None = Query(default=None, ge=0),
):
    return _run(
        lambda: request.app.state.plugins.revoke(
            plugin_id,
            permission,
            expected_revision=expected_revision,
        )
    )
