"""Acciones de correo de la pantalla: ver mia/api/mail_actions.py."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from mia.api.deps import ServicesDep, UserDep
from mia.api.mail_actions import ACTIONS, MailActionError, execute_mail_action

router = APIRouter(tags=["correo"], include_in_schema=False)


@router.post("/api/mail/{action}")
@router.post("/api/mia/mail/{action}")
async def mail_action(action: str, body: dict[str, Any], services: ServicesDep, user: UserDep) -> dict[str, Any]:
    if action not in ACTIONS:
        raise HTTPException(404, "Acción de correo desconocida")
    try:
        return await execute_mail_action(services, user, action, body)
    except MailActionError as exc:
        raise HTTPException(422, str(exc)) from exc
