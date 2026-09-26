from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from mia.data.repositories import SessionNotOwnedError
from mia.observability import current_request_id, get_logger

log = get_logger(__name__)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SessionNotOwnedError)
    async def _session_not_owned(_: Request, __: SessionNotOwnedError) -> JSONResponse:
        return JSONResponse(
            {"status": "forbidden", "answer": "Esa conversación no te pertenece."},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("http.unhandled_error", error_type=type(exc).__name__)
        return JSONResponse(
            {
                "status": "error",
                "answer": "No he podido completar la consulta por un error técnico.",
                "request_id": current_request_id(),
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
