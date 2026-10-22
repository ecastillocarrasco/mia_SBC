from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from mia.api.services import Services
from mia.auth import Permission, UserContext
from mia.auth.providers import AuthenticationError
from mia.observability import get_logger

log = get_logger(__name__)


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


async def get_user(request: Request, services: ServicesDep) -> UserContext:
    try:
        return await services.identity.authenticate(request)
    except AuthenticationError as exc:
        # El motivo real (falta cabecera, token mal formado, JWKS inalcanzable, audiencia/issuer
        # no coincide...) nunca llega al cliente -- el 401 siempre dice lo mismo, a propósito, para
        # no revelar detalle de validación a quien no está autenticado. Sin este log, ese motivo se
        # perdía del todo (ni en la respuesta ni en ningún otro sitio).
        log.warning("auth.rejected", reason=str(exc), path=request.url.path)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Necesitas iniciar sesión") from exc


UserDep = Annotated[UserContext, Depends(get_user)]


def require(permission: Permission) -> Callable[..., Awaitable[UserContext]]:
    """Dependencia que exige un permiso concreto (403 si no se tiene)."""

    async def dependency(user: UserDep) -> UserContext:
        if not user.has(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para esta operación")
        return user

    return dependency
