"""Qué buzón usa cada usuario.

  * ``configured`` (desarrollo): el buzón declarado en ``.env`` (MIA_MAIL__MAILBOX), el mismo para todos.
  * ``user`` (con autenticación MSAL/Entra ID): el buzón de la cuenta con la que el usuario ha iniciado sesión.

Las herramientas de correo NO reciben el buzón como parámetro: siempre sale de aquí, así ni el modelo ni
el usuario pueden apuntar a la bandeja de otra persona.
"""

from __future__ import annotations

from mia.auth import UserContext
from mia.settings import MailSettings


def resolve_mailbox(settings: MailSettings, user: UserContext) -> str | None:
    if settings.mailbox_source == "user":
        return (user.email or "").strip() or None
    return settings.mailbox.strip() or None


def mailbox_available(settings: MailSettings) -> bool:
    """¿Hay forma de resolver un buzón? (en modo «user» depende de quién inicie sesión)."""
    return settings.mailbox_source == "user" or bool(settings.mailbox.strip())
