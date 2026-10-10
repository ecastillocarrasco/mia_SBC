"""Configuración del módulo de diagnóstico."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiagnosticsSettings(BaseModel):
    enabled: bool = False
    """``MIA_DIAGNOSTICS__ENABLED=true`` activa captura completa, endpoints y panel.
    En false: overhead ≈ 0, ningún endpoint expuesto, ningún dato almacenado."""
    retention_hours: int = 24
    """Horas que se conservan las trazas en memoria (``MIA_DIAGNOSTICS__RETENTION_HOURS``)."""
    max_traces: int = 5000
    """Máximo de trazas en memoria antes de descartar las más antiguas (``MIA_DIAGNOSTICS__MAX_TRACES``)."""
    mask_pii: bool = False
    """Enmascara nombres, IDs y correos en las trazas (``MIA_DIAGNOSTICS__MASK_PII``).
    En desarrollo suele ser false para poder depurar; en preproducción/producción conviene true."""
    admin_users: list[str] = Field(default_factory=list)
    """Lista de user_id o email autorizados a ver el panel, además de los que tengan
    ``Permission.ADMINISTRAR`` (``MIA_DIAGNOSTICS__ADMIN_USERS=['user1@x.com']``)."""
