"""Fase G: ejecutor del trabajo en segundo plano "informe económico de nóminas" — conecta
`analisis_economico_nominas` con el Job Manager (`mia.reporting.job_manager`) para peticiones de gran
volumen, reutilizando exactamente las mismas dos herramientas ya registradas y validadas
(`analisis_economico_nominas` y `generar_informe`) a través del mismo `ToolRegistry` que usaría una
conversación real — nunca un camino paralelo ni una reconstrucción del motor analítico."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolStatus
from mia.conversation.tools import remember_table
from mia.llm import ToolCall
from mia.reporting.job_manager import JobSnapshot

JOB_KIND_INFORME_ECONOMICO = "informe_economico_nominas"


def _rebuild_user(params: dict[str, Any]) -> UserContext:
    """El trabajo se ejecuta fuera de cualquier turno de conversación: reconstruye el `UserContext` a
    partir de lo capturado EN EL MOMENTO DEL ENVÍO (este proyecto no tiene un directorio de usuarios al
    que consultar roles en vivo). Los roles son metadato de autorización, no datos personales ni de
    negocio — es la única información que `params_json` guarda sobre el usuario, bajo la clave `_auth`,
    separada a propósito del resto de parámetros de negocio (periodo, departamento, concepto…)."""
    auth = params.get("_auth") or {}
    return UserContext(
        user_id=auth.get("user_id", "desconocido"),
        display_name=auth.get("display_name", "Usuario"),
        roles=frozenset(auth.get("roles") or ()),
    )


async def run_informe_economico_nominas(services: Any, job: JobSnapshot) -> str:
    """Ejecuta de verdad `analisis_economico_nominas` y renderiza el resultado con `generar_informe` —
    ambas A TRAVÉS DEL MISMO `ToolRegistry` que usaría el LLM (`services.registry.execute()`), para no
    saltarse el permiso `NOMINAS_IMPORTES`, el trazado de diagnóstico ni el timeout de esa herramienta.
    El propio `ConversationEngine.run()` haría exactamente este mismo enlace entre ambas llamadas
    (`remember_table()` tras la primera, para que la segunda encuentre la tabla) — aquí se repite porque
    no hay ninguna conversación real detrás de un trabajo en segundo plano.

    Devuelve el ``report_id`` del informe generado; lanza una excepción en caso de fallo real (el
    ``ReportJobWorker`` llamante decide reintentar o marcar el trabajo como fallido)."""
    params = job.params
    user = _rebuild_user(params)
    now = datetime.now(ZoneInfo(services.settings.timezone))
    ctx = ToolContext(user=user, request_id=None, now=now, session_state={})

    eco_args = {
        "periodo": params["periodo"],
        "departamento": params.get("departamento"),
        "concepto": params.get("concepto", "liquido"),
        "incluir_grupos_pequenos": params.get("incluir_grupos_pequenos", False),
        "incluir_inactivos": params.get("incluir_inactivos", False),
    }
    eco_execution = await services.registry.execute(
        ToolCall(f"job:{job.id}:analisis", "analisis_economico_nominas", json.dumps(eco_args)), ctx
    )
    eco_result = eco_execution.result
    if eco_result.status is not ToolStatus.OK:
        detalle = eco_result.summary.get("mensaje") if isinstance(eco_result.summary, dict) else eco_result.summary
        raise RuntimeError(f"analisis_economico_nominas: {eco_result.status.value} — {detalle}")

    max_rows = services.settings.reports.max_rows if services.settings else 5000
    remember_table(ctx.session_state, eco_result.presentation, max_rows, eco_result.summary)

    informe_args = {
        "formato": params.get("formato", "pdf"),
        "titulo": params.get("titulo"),
        "incluir_detalle": True,
        "incluir_grafico": True,
        "incluir_narrativa": False,
    }
    informe_execution = await services.registry.execute(
        ToolCall(f"job:{job.id}:informe", "generar_informe", json.dumps(informe_args)), ctx
    )
    informe_result = informe_execution.result
    if informe_result.status is not ToolStatus.OK:
        raise RuntimeError(f"generar_informe: {informe_result.status.value} — {informe_result.summary}")
    # `generar_informe` construye el enlace como f"/api/reports/{report_id}" (ver informes/tools.py):
    # el propio informe ya lo recoge en la tabla `reports`, así que basta con el id para enlazarlo aquí.
    return informe_result.summary["enlace"].rsplit("/", 1)[-1]
