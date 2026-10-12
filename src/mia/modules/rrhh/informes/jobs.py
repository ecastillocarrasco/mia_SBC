"""Fase G: ejecutor del trabajo en segundo plano "informe económico de nóminas" — conecta
`analisis_economico_nominas` con el Job Manager (`mia.reporting.job_manager`) para peticiones de gran
volumen, reutilizando exactamente las mismas dos herramientas ya registradas y validadas
(`analisis_economico_nominas` y `generar_informe`) a través del mismo `ToolRegistry` que usaría una
conversación real — nunca un camino paralelo ni una reconstrucción del motor analítico."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from mia.auth import Permission, UserContext
from mia.conversation import Tool, ToolContext, ToolResult, ToolStatus
from mia.conversation.tools import remember_table
from mia.llm import ToolCall
from mia.modules.rrhh.common import Deps
from mia.reporting import job_manager
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
    ``ReportJobWorker`` llamante decide reintentar o marcar el trabajo como fallido).

    Fase I (cierre de seguridad): bloqueado de forma segura mientras
    ``settings.jobs.allow_sensitive_async`` sea ``False`` (su valor por defecto) — ningún proveedor
    de identidad de este sistema (dev/EasyAuth/Entra ID) permite consultar en vivo, desde este worker
    sin una petición HTTP real, si los roles capturados en ``params["_auth"]`` al encolar el trabajo
    siguen vigentes. Hasta que exista esa fuente verificable, la ejecución asíncrona de informes
    económicos queda deshabilitada — nunca se ejecuta con una autorización que podría estar obsoleta."""
    if not getattr(getattr(services.settings, "jobs", None), "allow_sensitive_async", False):
        raise RuntimeError(
            "permission_denied: ejecución asíncrona de informes económicos deshabilitada "
            "(MIA_JOBS__ALLOW_SENSITIVE_ASYNC=false) hasta validar autorizaciones vigentes — "
            "pide el informe sin 'en segundo plano' para la ruta síncrona, ya autorizada"
        )
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
    remember_table(
        ctx.session_state, eco_result.presentation, max_rows, eco_result.summary,
        source_tool="analisis_economico_nominas",
    )

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


# ------------------------------------------------------------------ punto de entrada conversacional


class InformeEconomicoJobParams(BaseModel):
    """Mismos campos que ``SubmitInformeEconomicoParams`` (``src/mia/api/routes/jobs.py``) — un único
    contrato de negocio para el trabajo, enviado desde el chat o desde el endpoint REST directo; nunca
    dos formas distintas de describir el mismo trabajo."""

    periodo: str = Field(description="Expresión temporal: 'T3 2026', 'agosto 2026', 'últimos 6 meses'…")
    departamento: str | None = Field(default=None, description="Limitar a un departamento; vacío = todos")
    concepto: Literal["liquido", "devengado", "coste_empresa"] = "liquido"
    incluir_grupos_pequenos: bool = False
    incluir_inactivos: bool = False
    formato: Literal["pdf", "xlsx", "pptx", "html"] = "pdf"
    titulo: str | None = None


def informe_economico_en_segundo_plano(deps: Deps) -> Tool:
    """Fase H, "integración del Job Manager en el mundo 2D real": punto de entrada conversacional al
    MISMO Job Manager y ejecutor ya construidos en la Fase G (`job_manager.submit`,
    `run_informe_economico_nominas`) — nunca una segunda cola ni un segundo gestor de trabajos. El
    endpoint REST directo (`POST /api/jobs/informe-economico`) y esta herramienta comparten
    exactamente el mismo `kind`, los mismos parámetros y la misma clave de idempotencia determinista."""

    async def handler(p: InformeEconomicoJobParams, ctx: ToolContext) -> ToolResult:
        if not getattr(getattr(deps.settings, "jobs", None), "allow_sensitive_async", False):
            return ToolResult(
                ToolStatus.PERMISSION_DENIED,
                {
                    "mensaje": (
                        "El procesamiento en segundo plano de informes económicos está deshabilitado "
                        "mientras no exista una comprobación fiable de permisos vigentes para un trabajo "
                        "en cola. Pide el informe sin 'en segundo plano': la ruta directa ya está "
                        "autorizada y funciona con normalidad."
                    )
                },
            )
        params = p.model_dump()
        params["_auth"] = {
            "user_id": ctx.user.user_id,
            "display_name": ctx.user.display_name,
            "roles": sorted(ctx.user.roles),
        }
        business_params = {k: v for k, v in params.items() if k != "_auth"}
        idempotency_key = hashlib.sha256(
            json.dumps({"user_id": ctx.user.user_id, **business_params}, sort_keys=True).encode("utf-8")
        ).hexdigest()
        async with deps.db.session() as db:
            job_id = await job_manager.submit(
                db,
                user_id=ctx.user.user_id,
                kind=JOB_KIND_INFORME_ECONOMICO,
                params=params,
                idempotency_key=idempotency_key,
            )
            snapshot = await job_manager.get(db, job_id)
        assert snapshot is not None  # noqa: S101 — se acaba de crear/recuperar en la misma transacción
        return ToolResult(
            ToolStatus.OK,
            {
                "job_id": snapshot.id,
                "estado": snapshot.status,
                "mensaje": (
                    "He encolado el análisis económico en segundo plano. Puedo avisarte del progreso "
                    "o puedes consultarlo cuando quieras — también queda guardado si recargas la página."
                ),
            },
            {
                "type": "job",
                "job_id": snapshot.id,
                "kind": snapshot.kind,
                "status": snapshot.status,
                "periodo": p.periodo,
                "formato": p.formato,
            },
        )

    return Tool(
        "informe_economico_en_segundo_plano",
        "Encola el análisis económico de nóminas y su informe como trabajo en SEGUNDO PLANO, con "
        "progreso real consultable y descarga cuando termine. Úsala SOLO cuando el usuario pida "
        "explícitamente procesarlo 'en segundo plano'/'en background'/'que tarde lo que tarde, avísame' "
        "o para un volumen muy grande (muchos meses/departamentos) que el usuario prefiera no esperar "
        "en el propio turno. Para la petición normal, usa 'analisis_economico_nominas' directamente — "
        "esta herramienta nunca sustituye a esa por defecto.",
        InformeEconomicoJobParams,
        handler,
        permission=Permission.NOMINAS_IMPORTES,
        audit_resource="nominas_importes",
    )
