"""レスポンスにセキュリティ関連 HTTP ヘッダーを付与するミドルウェア.

Market Lens `backend/services/security_headers.py` から移植。変更点:
- Alpha Forge のバックエンドが返す HTML は FastAPI 標準の `/docs` `/redoc` のみ。
  実際にブラウザへ画面を配信するのは Next.js 側であり、nonce ベース CSP は
  frontend の middleware（`frontend/src/middleware.ts`）が担当する。
- ここでは JSON API 応答向けの厳格 CSP と、`/docs` 向けの緩和 CSP を出し分ける。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from backend.config import settings

_STATIC_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# JSON API 応答向けの厳格 CSP（HTML を返さない前提の多層防御）。
_API_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "frame-src 'none'; "
    "object-src 'none'; "
    "base-uri 'self'"
)

# `/docs`（Swagger UI）/ `/redoc` 専用の緩和 CSP（CDN 読込 + 初期化インラインスクリプト）。
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "base-uri 'self'"
)

_CSP_HEADER = "Content-Security-Policy"
_HSTS_HEADER = "Strict-Transport-Security"
_HSTS_VALUE = "max-age=31536000; includeSubDomains"


def _is_docs_path(path: str) -> bool:
    """Swagger UI / ReDoc の HTML 面かどうかを判定する（サブパスも含める）."""
    return path in ("/docs", "/redoc") or path.startswith(("/docs/", "/redoc/"))


def register_security_headers(app: FastAPI) -> None:
    """全レスポンスに固定セキュリティヘッダーを付与するミドルウェアを登録する."""

    @app.middleware("http")
    async def _security_headers_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for key, value in _STATIC_HEADERS.items():
            response.headers.setdefault(key, value)
        csp_value = _DOCS_CSP if _is_docs_path(request.url.path) else _API_CSP
        response.headers.setdefault(_CSP_HEADER, csp_value)
        if settings.cookie_secure:
            response.headers.setdefault(_HSTS_HEADER, _HSTS_VALUE)
        return response
