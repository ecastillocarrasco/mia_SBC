from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from mia.api.services import Services
from mia.auth import Permission, UserContext
from mia.auth.providers import AuthenticationError


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


async def get_user(request: Request, services: ServicesDep) -> UserContext:
    try:
        return await services.identity.authenticate(request)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Necesitas iniciar sesión") from exc


UserDep = Annotated[UserContext, Depends(get_user)]


def require(permission: Permission) -> Callable[..., Awaitable[UserContext]]:
    """Dependencia que exige un permiso concreto (403 si no se tiene)."""

    async def dependency(user: UserDep) -> UserContext:
        if not user.has(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para esta operación")
        return user

    return dependency
