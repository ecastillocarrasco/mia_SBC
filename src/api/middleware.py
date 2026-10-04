from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from mia.observability import get_logger, new_request_id

log = get_logger("mia.http")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "SAMEORIGIN",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Identificador de correlación, cabeceras de seguridad y log de acceso."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = new_request_id(request.headers.get("x-request-id"))
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if not request.url.path.startswith(("/health", "/mia-assets")):
            log.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        return response
