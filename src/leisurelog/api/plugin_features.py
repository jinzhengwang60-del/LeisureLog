"""Generic presentation adapter for reviewed host bindings, never plugin routers."""

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.routing import compile_path

from leisurelog.domain.plugin_extensions import AnalysisRejected
from leisurelog.services.plugin_access import PluginAccessDenied
from leisurelog.services.plugin_runtime import PluginOperationError

router = APIRouter()
_UNAVAILABLE = """<!doctype html><html lang="zh-CN"><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeisureLog · 功能暂时不可用</title><body><main>
<h1>这个功能暂时不可用</h1><p>相关插件已停用、出现故障或尚未启用。
你的活动记录和人工修正仍然保留，可以在插件状态中检查原因。</p>
<p><a href="/">返回活动记录</a> · <a href="/plugins">查看插件管理</a></p>
</main></body></html>"""


def _error(error):
    if isinstance(error, AnalysisRejected):
        raise HTTPException(error.status, error.message) from None
    if isinstance(error, ValidationError):
        raise HTTPException(
            422,
            jsonable_encoder(
                error.errors(),
                custom_encoder={
                    ValueError: str,
                },
            ),
        ) from None
    if isinstance(error, KeyError):
        raise HTTPException(404, "条目或页面资源不存在，请刷新") from None
    if isinstance(error, ValueError):
        raise HTTPException(422, str(error)) from None
    raise HTTPException(
        503, {"code": "extension_unavailable", "message": "功能插件已停用、失效或暂时繁忙"}
    ) from None


def _resource(request, owner, *, name=None, asset=None):
    try:
        data, media = request.app.state.plugin_pages.read(owner, name=name, asset=asset)
        return Response(data, media_type=media, headers={"Cache-Control": "no-store"})
    except (PluginOperationError, PluginAccessDenied):
        if name is not None:
            return HTMLResponse(
                _UNAVAILABLE,
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        raise HTTPException(503, "页面资源已停用") from None
    except (KeyError, ValueError) as error:
        _error(error)


@router.get("/api/plugin-navigation")
def navigation(request: Request):
    return request.app.state.plugin_pages.navigation()


@router.get("/plugins/{plugin_id}/pages/{name}", include_in_schema=False)
def plugin_page(plugin_id: str, name: str, request: Request):
    return _resource(request, plugin_id, name=name)


@router.get("/plugin-assets/{plugin_id}/{asset:path}", include_in_schema=False)
def plugin_asset(plugin_id: str, asset: str, request: Request):
    return _resource(request, plugin_id, asset=asset)


def _handler(endpoint):
    async def dispatch(request: Request):
        try:
            if len(set(request.query_params)) != len(request.query_params.multi_items()):
                raise ValueError("同一个查询参数不能重复")
            if len(request.url.query.encode("utf-8")) > 16384:
                raise ValueError("查询参数过长")
            parameters = endpoint.query_type.model_validate(dict(request.query_params)).model_dump(
                mode="json"
            )
            parameters.update(request.path_params)
            if endpoint.body_type is not None:
                payload = bytearray()
                async for chunk in request.stream():
                    payload.extend(chunk)
                    if len(payload) > 16384:
                        raise HTTPException(413, "请求内容最多 16 KiB")
                parameters["body"] = endpoint.body_type.model_validate_json(payload).model_dump(
                    mode="json"
                )
            return await run_in_threadpool(
                request.app.state.extensions.execute,
                endpoint,
                parameters,
            )
        except (
            AnalysisRejected,
            ValidationError,
            KeyError,
            ValueError,
            PluginOperationError,
            PluginAccessDenied,
        ) as error:
            _error(error)

    return dispatch


def _page_handler(page):
    def dispatch(request: Request):
        return _resource(request, page.owner, name=page.name)

    return dispatch


def _schema(endpoint):
    model = endpoint.query_type.model_json_schema()
    params = [
        {
            "name": name,
            "in": "query",
            "schema": schema,
            "required": name in model.get("required", []),
        }
        for name, schema in model.get("properties", {}).items()
    ]
    params.extend(
        {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}
        for name in re.findall(r"\{([^}:]+)(?::[^}]+)?\}", endpoint.path)
    )
    extra = {"parameters": params, "responses": {"503": {"description": "插件功能不可用"}}}
    if endpoint.body_type is not None:
        extra["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {"schema": endpoint.body_type.model_json_schema()},
            },
        }
    return extra


def _route_shapes(app):
    # FastAPI supports both eager routes and included routers with effective
    # contexts. Use their computed paths, including prefixes and hidden pages.
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            for context in contexts():
                yield context.starlette_route or context
        elif hasattr(route, "path"):
            yield route
        else:
            raise ValueError("无法检查宿主路由，拒绝登记插件 URL")


def install_feature_routes(app, endpoints, pages):
    bindings = [(value.path, value.method, value) for value in endpoints]
    bindings.extend((value.path, "GET", value) for value in pages)
    for path, method, value in bindings:
        regex, _, _ = compile_path(path)
        sample = re.sub(r"\{[^}]+\}", "sample", path)
        for route in _route_shapes(app):
            route_methods = getattr(route, "methods", None)
            if route_methods is not None and method not in route_methods:
                continue
            other_sample = re.sub(r"\{[^}]+\}", "sample", route.path)
            if (
                route.path_regex.fullmatch(sample)
                or regex.fullmatch(other_sample)
                or (
                    route_methods is None
                    and (path == route.path or path.startswith(route.path + "/"))
                )
            ):
                raise ValueError("插件 URL 与已有宿主路由冲突")
        is_endpoint = hasattr(value, "method")
        app.add_api_route(
            path,
            _handler(value) if is_endpoint else _page_handler(value),
            methods=[method],
            name=f"{value.owner}.{value.name}.{method}",
            include_in_schema=is_endpoint,
            tags=["plugin-analysis"] if is_endpoint else None,
            openapi_extra=_schema(value) if is_endpoint else None,
        )
