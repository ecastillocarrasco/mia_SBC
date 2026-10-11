"""Inspección de lo que devuelve el LLM antes de que llegue al usuario.

No se trata la respuesta del modelo como instrucciones ejecutables en ningún caso — esto solo
inspecciona texto para bloquear fugas (secretos) y lo deja pasar; la restauración de tokens reversibles
la hace `Tokenizer.restore()`, con su propio control de autorización por operación/usuario.
"""

from __future__ import annotations

from mia.privacy_gateway.outbound_inspector import contains_secret, redact_secrets


def sanitize_inbound(text: str) -> tuple[str, bool]:
    """Devuelve (texto_seguro, se_detectó_algo). Si el LLM devuelve un secreto (p. ej. porque lo copió de
    un documento adjunto malicioso), se redacta igual que en la dirección de salida."""
    if not text:
        return text, False
    if not contains_secret(text):
        return text, False
    cleaned, _ = redact_secrets(text)
    return cleaned, True
