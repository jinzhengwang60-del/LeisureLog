"""Loopback binding plus an authenticated local session and source checks."""

import hashlib
import hmac

from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse


def secure_local_app(app, token: str, origin: str, profile_key: str):
    cookie = "leisurelog_" + hashlib.sha256(profile_key.encode()).hexdigest()[:12]

    def valid(value):
        return bool(value) and value.isascii() and hmac.compare_digest(value, token)

    @app.middleware("http")
    async def local_session(request, call_next):
        if request.headers.get("host") != origin.split("//", 1)[1]:
            return JSONResponse({"detail": "仅允许本机访问"}, status_code=403)
        if (
            request.headers.get("origin", origin) != origin
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "请求来源未获允许"}, status_code=403)
        if request.url.path == "/_desktop/open":
            if not valid(request.query_params.get("token")):
                return JSONResponse({"detail": "请从桌面图标打开 LeisureLog"}, status_code=401)
            destination = (
                "/setup"
                if request.query_params.get("page") == "setup"
                or not app.state.desktop.preferences.setup_completed
                else "/"
            )
            response = RedirectResponse(destination, status_code=303)
            response.set_cookie(cookie, token, httponly=True, samesite="strict", path="/")
        elif valid(request.cookies.get(cookie)) or valid(
            request.headers.get("authorization", "").removeprefix("Bearer ")
        ):
            if (
                not app.state.desktop.preferences.setup_completed
                and request.url.path.startswith("/api/")
                and request.method not in {"GET", "HEAD"}
            ):
                response = JSONResponse({"detail": "请先完成首次使用引导"}, status_code=409)
            else:
                response = await call_next(request)
        elif request.method == "GET" and not request.url.path.startswith(("/api/", "/_desktop/")):
            response = HTMLResponse(
                '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                '<title>打开 LeisureLog</title><body style="font:18px system-ui;padding:64px">'
                "<h1>从桌面图标打开 LeisureLog</h1>"
                "<p>也可以右键系统托盘图标，选择“打开活动记录”。</p></body></html>",
                status_code=401,
            )
        else:
            response = JSONResponse({"detail": "本地会话未连接"}, status_code=401)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            }
        )
        return response
