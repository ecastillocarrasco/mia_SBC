"""Excepciones del Privacy Gateway. Nunca deben llevar el valor sensible en el mensaje."""

from __future__ import annotations


class PrivacyGatewayError(Exception):
    """Base de cualquier fallo del gateway."""


class UnsafeContentBlockedError(PrivacyGatewayError):
    """La política de fallo seguro bloqueó la llamada externa (p. ej. Presidio falló y fail_open=False,
    o se detectó un secreto que no puede enviarse de ninguna forma)."""


class RestorationDeniedError(PrivacyGatewayError):
    """Un token no se restauró: no existe, caducó, pertenece a otro contexto o la política lo prohíbe."""
