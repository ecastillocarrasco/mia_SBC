"""Resolución del buzón personal por usuario.

Las herramientas pueden recibir el UPN o dirección de un buzón compartido. Con OBO,
Microsoft Graph/Exchange decide si el usuario conectado está autorizado para acceder.
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
