"""mia_privacy_gateway — capa centralizada de protección de datos para toda llamada al proveedor LLM.

API pública:

    from mia.privacy_gateway import PrivacyGateway

En la práctica, nadie debería instanciar ``PrivacyGateway`` directamente fuera de
``mia.llm.factory.build_llm_provider`` — ese es el único punto de construcción legítimo, y es lo que
garantiza que no haya una ruta alternativa para hablar con el proveedor sin pasar por aquí.

Estado (ver PRIVACY_GATEWAY_PROGRESS.md en la raíz del repositorio para el detalle completo):
  Etapa 1 — Centralización + Presidio + fallo seguro: HECHO.
  Etapa 2 — Reconocedores españoles, políticas, Token Vault, restauración: HECHO (nivel inicial).
  Etapa 3 — Secretos, inspección de respuesta: HECHO (nivel inicial); prompt-injection avanzado: PENDIENTE.
  Etapa 4 — Migración de TODAS las rutas LLM: el punto de construcción único ya cubre chat, herramientas
            y narrativa; embeddings e imágenes están explícitamente documentados como pendientes/bloqueados.
  Etapa 5 — Pruebas globales de integración/aislamiento/rendimiento: EN CURSO (ver tests/test_privacy_gateway.py).
  Etapa 6 — Documentación para módulos futuros: este docstring + PRIVACY_GATEWAY_PROGRESS.md.
"""

from __future__ import annotations

from mia.privacy_gateway.exceptions import PrivacyGatewayError, RestorationDeniedError, UnsafeContentBlockedError
from mia.privacy_gateway.gateway import PrivacyGateway
from mia.privacy_gateway.policy_engine import Policy

__all__ = [
    "Policy",
    "PrivacyGateway",
    "PrivacyGatewayError",
    "RestorationDeniedError",
    "UnsafeContentBlockedError",
]
