from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from mia import __version__
from mia.api.deps import ServicesDep

router = APIRouter(tags=["salud"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    """El proceso está vivo (sonda de liveness de Container Apps)."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(services: ServicesDep) -> JSONResponse:
    """Listo para atender: la base de datos responde (sonda de readiness)."""
    db_ok = await services.db.ping()
    body = {"status": "ok" if db_ok else "degraded", "database": db_ok, "version": __version__}
    return JSONResponse(body, status_code=200 if db_ok else 503)
