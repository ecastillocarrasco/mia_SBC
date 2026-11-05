"""Plan explícito del turno y comprobación de evidencia, sin conceder permisos.

El modelo propone pasos; solo ejecuciones reales satisfacen sus requisitos.
El contrato de formatos procede de la petición y no puede reducirlo el plan.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from mia.conversation.argument_contracts import normalize_arguments, normalize_plan_arguments
from mia.conversation.tools import Tool, ToolContext, ToolExecution, ToolRegistry, ToolResult, ToolStatus
from mia.llm import ToolCall, ToolSchema
from mia.reporting.delivery import download_formats, requested_formats
from mia.text import normalize_key

PLAN_TOOL = "planificar_tarea"


class IncompleteReason(StrEnum):
    """Por qué un paso del plan no quedó verificado, en categorías que el usuario puede entender.

    Deliberadamente más finas que las cuatro nombradas en el encargo (fallo de fuente,
    insuficiencia de datos, aclaración necesaria, objetivo cumplido): PERMISO_DENEGADO y
    EJECUCION_PENDIENTE son estados reales que no encajan limpiamente en ninguna de esas
    cuatro sin inducir a error, así que se mantienen separados en vez de forzarlos dentro.
    """

    FUENTE_NO_DISPONIBLE = "fuente_no_disponible"
    PERMISO_DENEGADO = "permiso_denegado"
    ACLARACION_NECESARIA = "aclaracion_necesaria"
    DATOS_INSUFICIENTES = "datos_insuficientes"
    VERIFICACION_PENDIENTE = "verificacion_pendiente"
    EJECUCION_PENDIENTE = "ejecucion_pendiente"


_REASON_BY_STATUS: dict[ToolStatus, IncompleteReason] = {
    ToolStatus.SOURCE_UNAVAILABLE: IncompleteReason.FUENTE_NO_DISPONIBLE,
    ToolStatus.ERROR: IncompleteReason.FUENTE_NO_DISPONIBLE,
    ToolStatus.PERMISSION_DENIED: IncompleteReason.PERMISO_DENEGADO,
    ToolStatus.AMBIGUOUS: IncompleteReason.ACLARACION_NECESARIA,
    ToolStatus.INVALID_ARGUMENTS: IncompleteReason.ACLARACION_NECESARIA,
    ToolStatus.NOT_FOUND: IncompleteReason.DATOS_INSUFICIENTES,
}
"""Prioridad de mayor a menor cuando varias herramientas del mismo paso fallan de forma distinta:
permiso denegado pesa más que un fallo de fuente, que pesa más que una aclaración, que pesa más
que datos insuficientes — refleja qué causa bloquea más la tarea, no el orden de ejecución."""
_REASON_PRIORITY = (
    IncompleteReason.PERMISO_DENEGADO,
    IncompleteReason.FUENTE_NO_DISPONIBLE,
    IncompleteReason.ACLARACION_NECESARIA,
    IncompleteReason.DATOS_INSUFICIENTES,
)
_REASON_TEXT: dict[IncompleteReason, str] = {
    IncompleteReason.FUENTE_NO_DISPONIBLE: "la fuente de datos no respondió o falló al consultarla",
    IncompleteReason.PERMISO_DENEGADO: "no hay permiso para consultar esa fuente",
    IncompleteReason.ACLARACION_NECESARIA: "la petición necesita que aclares a qué te refieres",
    IncompleteReason.DATOS_INSUFICIENTES: "no hay datos suficientes para esa consulta",
    IncompleteReason.VERIFICACION_PENDIENTE: "aún falta comprobar el resultado",
    IncompleteReason.EJECUCION_PENDIENTE: "no se llegó a completar dentro de este turno",
}


@dataclass(frozen=True, slots=True)
class IncompleteStep:
    objetivo: str
    reason: IncompleteReason
    detail: str


def incomplete_detail_lines(steps: list[IncompleteStep]) -> list[str]:
    """Líneas en lenguaje llano, una por paso: nunca identificadores internos de paso/herramienta."""
    return [f"- «{s.objetivo}»: {s.detail}." for s in steps]


def compose_incomplete_message(steps: list[IncompleteStep]) -> str:
    if not steps:
        return ""
    return "La tarea quedó incompleta:\n" + "\n".join(incomplete_detail_lines(steps))


def population_context_question(ctx: ToolContext) -> str | None:
    if not re.search(r"\b(?:grupo|seleccion) anterior\b", normalize_key(ctx.user_message)):
        return None
    if ctx.session_state.get("ultima_poblacion") or ctx.session_state.get("historial_poblaciones"):
        return None
    return (
        "No hay una selección anterior de personas en esta sesión. Indica qué personas o departamento quieres comparar."
    )


class TaskStep(BaseModel):
    objetivo: str = Field(min_length=1, max_length=200)
    herramientas: list[str] = Field(min_length=1, max_length=6)
    depende_de: list[int] = Field(default_factory=list, max_length=7)
    argumentos: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description='Filtros POR HERRAMIENTA. Ejemplo: {"plantilla":{"departamento":"Cocina"}}. '
        "Con varias herramientas, cada una debe tener su propio objeto de argumentos.",
    )

    @model_validator(mode="before")
    @classmethod
    def single_tool_arguments(cls, data: Any) -> Any:
        """Un solo destinatario permite normalizar argumentos planos sin perder filtros."""
        if not isinstance(data, dict):
            return data
        names, args = data.get("herramientas"), data.get("argumentos")
        if (
            isinstance(names, list)
            and len(names) == 1
            and isinstance(names[0], str)
            and isinstance(args, dict)
            and args
            and names[0] not in args
        ):
            return {**data, "argumentos": {names[0]: args}}
        if (
            isinstance(names, list)
            and len(names) > 1
            and isinstance(args, dict)
            and any(name not in names or not isinstance(value, dict) for name, value in args.items())
        ):
            raise ValueError(
                'Indica los argumentos por herramienta: {"plantilla":{"departamento":"Cocina"}, '
                '"vacaciones":{"departamento":"Cocina"}}; no se reparten filtros ambiguos.'
            )
        return data


class TaskSteps(BaseModel):
    pasos: list[TaskStep] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def ordered_dependencies(self) -> TaskSteps:
        if len({step.objetivo for step in self.pasos}) != len(self.pasos):
            raise ValueError("Cada paso necesita un objetivo distinto")
        for index, step in enumerate(self.pasos):
            if any(dependency < 0 or dependency >= index for dependency in step.depende_de):
                raise ValueError("Las dependencias deben apuntar a pasos anteriores (índices desde cero)")
            if set(step.argumentos) - set(step.herramientas):
                raise ValueError("Los argumentos deben pertenecer a las herramientas del paso")
        return self


@dataclass(frozen=True, slots=True)
class _PlanningTool(Tool):
    available_names: tuple[str, ...] = ()

    def schema(self) -> ToolSchema:
        schema = Tool.schema(self)
        if self.available_names:
            names_schema = schema.parameters["$defs"]["TaskStep"]["properties"]["herramientas"]["items"]
            names_schema["enum"] = list(self.available_names)
        return schema


@dataclass
class TaskPlan:
    request: str
    available: frozenset[str]
    steps: list[TaskStep] = field(default_factory=list)
    revisions: int = 0
    parameter_models: dict[str, type[BaseModel]] = field(default_factory=dict, repr=False)
    required_verifiers: frozenset[str] = frozenset()
    today: date | None = None

    def tool(self) -> Tool:
        async def propose(params: TaskSteps, ctx: ToolContext) -> ToolResult:
            unknown = {name for step in params.pasos for name in step.herramientas} - self.available
            unknown |= self.required_verifiers - {name for step in params.pasos for name in step.herramientas}
            if unknown or any(PLAN_TOOL in step.herramientas for step in params.pasos):
                return ToolResult(
                    ToolStatus.INVALID_ARGUMENTS,
                    {
                        "mensaje": "El plan usa herramientas no disponibles o le faltan verificadores obligatorios.",
                        "verificadores_obligatorios": sorted(self.required_verifiers),
                    },
                )
            if self.revisions >= 2:
                return ToolResult(
                    ToolStatus.INVALID_ARGUMENTS, {"mensaje": "Se ha alcanzado el límite de replanteamiento."}
                )
            for step in params.pasos:
                for name, arguments in step.argumentos.items():
                    model = self.parameter_models.get(name)
                    if model is None:
                        continue
                    try:
                        step.argumentos[name] = normalize_plan_arguments(
                            model, arguments, ctx.user_message, ctx.now.date()
                        )
                    except (ValueError, TypeError):
                        return ToolResult(
                            ToolStatus.INVALID_ARGUMENTS,
                            {
                                "mensaje": "Corrige los filtros del plan usando el esquema de la herramienta.",
                                "herramienta": name,
                                "campos_admitidos": sorted(model.model_fields),
                            },
                        )
            previous_goals = {step.objetivo for step in self.steps}
            if not previous_goals.issubset({step.objetivo for step in params.pasos}):
                return ToolResult(
                    ToolStatus.INVALID_ARGUMENTS,
                    {"mensaje": "Al replantear hay que conservar los objetivos pendientes del plan original."},
                )
            revised = {step.objetivo: step for step in params.pasos}
            for old in self.steps:
                for name, constraints in old.argumentos.items():
                    replacement = revised[old.objetivo]
                    candidates = (
                        [replacement.argumentos.get(name, {})]
                        if name in replacement.herramientas
                        else [args for step in params.pasos for args in step.argumentos.values()]
                    )
                    if any(
                        not any(key in args and args[key] == value for args in candidates)
                        for key, value in constraints.items()
                    ):
                        return ToolResult(
                            ToolStatus.INVALID_ARGUMENTS,
                            {"mensaje": "El replanteamiento no puede cambiar ni eliminar los filtros ya declarados."},
                        )
            self.steps = params.pasos
            self.revisions += 1
            return ToolResult.ok({"plan": [step.model_dump() for step in self.steps], "revision": self.revisions})

        return _PlanningTool(
            PLAN_TOOL,
            "Antes de una tarea compleja, declara los pasos, herramientas necesarias y dependencias. "
            "Cada paso exige TODAS sus herramientas. Índices desde cero. No ejecuta acciones ni autoriza datos. "
            "Declara en argumentos los filtros esenciales por herramienta (periodo, departamento o selección). "
            "Puedes corregir el plan una vez ante resultados insuficientes; conserva todo lo pedido por el usuario. "
            "Puedes sustituir una herramienta inadecuada manteniendo el objetivo textual y todos los filtros; "
            "los filtros de datos deben quedar en una consulta compatible del plan. "
            "Catálogo autorizado de nombres para planificar: " + ", ".join(sorted(self.available)) + ". "
            "Si un nombre no estaba ofrecido inicialmente, su esquema se ofrecerá al aceptar el plan.",
            TaskSteps,
            propose,
            available_names=tuple(sorted(self.available)),
        )

    def instructions(self) -> str:
        return (
            (
                "\nVerificadores de lectura obligatorios para esta operación: "
                + ", ".join(sorted(self.required_verifiers))
                + ". "
                if self.required_verifiers
                else ""
            )
            + "\nPLAN DE EJECUCIÓN DEL TURNO: 1) obtener evidencia de las fuentes autorizadas; "
            "2) realizar los análisis solicitados con herramientas; 3) producir todos los entregables; "
            "4) verificar resultados y explicar lo que falte. Para descomponer una tarea compleja usa "
            f"{PLAN_TOOL} en una ronda separada, antes de ejecutar sus pasos. "
            "Los pasos deben cubrir TODA la petición, sin inventar fuentes, permisos ni resultados. "
            "Un error, resultado vacío o falta de datos exige corregir el recorrido o declarar la limitación. "
            "No repitas operaciones de escritura para intentar recuperar una respuesta."
        )

    def missing(self, executions: list[ToolExecution]) -> list[str]:
        """Cumplimiento estructural; no equivale a certificar semánticamente toda la prosa."""
        # Las respuestas de herramientas conservan el orden pedido por el modelo;
        # las dependencias se comprueban sobre el orden REAL de ejecución.
        executions = sorted(executions, key=lambda execution: execution.started_at)
        observed = {e.call.name for e in executions if e.result.status is ToolStatus.OK}
        missing: list[str] = [
            f"paso obligatorio: verificador {name} pendiente" for name in sorted(self.required_verifiers - observed)
        ]
        completed: dict[int, int] = {}
        for index, step in enumerate(self.steps):
            floor = max((completed.get(dependency, -1) for dependency in step.depende_de), default=-1)
            if any(dependency not in completed for dependency in step.depende_de):
                missing.append(f"paso {index + 1}: dependencia pendiente")
                continue
            positions = []
            for name in step.herramientas:
                position = next(
                    (
                        pos
                        for pos, execution in enumerate(executions)
                        if pos > floor
                        and execution.call.name == name
                        and execution.result.status is ToolStatus.OK
                        and _matching_arguments(
                            execution,
                            step.argumentos.get(name, {}),
                            self.parameter_models.get(name),
                            self.today,
                            self.request,
                        )
                    ),
                    None,
                )
                if position is None:
                    break
                positions.append(position)
            if len(positions) == len(step.herramientas):
                completed[index] = max(positions)
            else:
                missing.append(f"paso {index + 1}: sin evidencia de ejecución completa")
        delivered = download_formats(executions)
        missing += [f"archivo {fmt} pendiente" for fmt in requested_formats(self.request) if fmt not in delivered]
        return missing

    def incomplete_steps(self, executions: list[ToolExecution]) -> list[IncompleteStep]:
        """Como :meth:`missing`, pero en categorías y texto que el usuario puede entender.

        No sustituye a ``missing()`` (que sigue siendo la fuente de verdad estructural usada por
        la recuperación acotada y sus pruebas); es una segunda lectura de los MISMOS hechos para
        la respuesta final, nunca identificadores de paso/herramienta.
        """
        executions = sorted(executions, key=lambda execution: execution.started_at)
        observed = {e.call.name for e in executions if e.result.status is ToolStatus.OK}
        result = [
            IncompleteStep(
                objetivo=f"Verificación obligatoria: {name.replace('_', ' ')}",
                reason=IncompleteReason.VERIFICACION_PENDIENTE,
                detail=_REASON_TEXT[IncompleteReason.VERIFICACION_PENDIENTE],
            )
            for name in sorted(self.required_verifiers - observed)
        ]
        completed: dict[int, int] = {}
        for index, step in enumerate(self.steps):
            floor = max((completed.get(dependency, -1) for dependency in step.depende_de), default=-1)
            if any(dependency not in completed for dependency in step.depende_de):
                blocked = IncompleteReason.EJECUCION_PENDIENTE
                result.append(IncompleteStep(step.objetivo, blocked, _REASON_TEXT[blocked]))
                continue
            positions = []
            attempted_statuses: list[ToolStatus] = []
            for name in step.herramientas:
                position = None
                for pos, execution in enumerate(executions):
                    if pos <= floor or execution.call.name != name:
                        continue
                    attempted_statuses.append(execution.result.status)
                    arguments = step.argumentos.get(name, {})
                    model = self.parameter_models.get(name)
                    if execution.result.status is ToolStatus.OK and _matching_arguments(
                        execution, arguments, model, self.today, self.request
                    ):
                        position = pos
                        break
                if position is not None:
                    positions.append(position)
            if len(positions) == len(step.herramientas):
                completed[index] = max(positions)
                continue
            reason = next(
                (r for r in _REASON_PRIORITY if r in {_REASON_BY_STATUS.get(s) for s in attempted_statuses}),
                IncompleteReason.EJECUCION_PENDIENTE,
            )
            result.append(IncompleteStep(step.objetivo, reason, _REASON_TEXT[reason]))
        return result

    def pending_reads(self, executions: list[ToolExecution], reviewed: set[str], attempted: set[str]) -> list[ToolCall]:
        calls: dict[str, ToolCall] = {}
        failed_sources = {
            e.call.name
            for e in executions
            if e.result.status in {ToolStatus.SOURCE_UNAVAILABLE, ToolStatus.PERMISSION_DENIED, ToolStatus.ERROR}
        }
        for step in self.steps:
            for name in step.herramientas:
                model = self.parameter_models.get(name)
                if name not in reviewed or name in failed_sources or model is None:
                    continue
                try:
                    arguments = normalize_arguments(model, step.argumentos.get(name, {}), partial=False)
                except (ValueError, TypeError):
                    continue
                if any(
                    e.call.name == name
                    and e.result.status is ToolStatus.OK
                    and _matching_arguments(e, step.argumentos.get(name, {}), model, self.today, self.request)
                    for e in executions
                ):
                    continue
                serialized = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
                signature = name + serialized
                call = ToolCall(f"verify_plan_{len(executions)}_{len(calls)}", name, serialized)
                if signature not in attempted and self.ready(call, executions):
                    calls[signature] = call
        return list(calls.values())

    def ready(self, call: ToolCall, executions: list[ToolExecution]) -> bool:
        """Un paso declarado solo se ejecuta tras sus dependencias y con sus filtros."""
        matching = [step for step in self.steps if call.name in step.herramientas]
        if not matching:
            return True  # consultas auxiliares mantienen los permisos del registro
        probe = ToolExecution(call, ToolResult.ok({}), 0, None)
        for step in matching:
            if not _matching_arguments(
                probe,
                step.argumentos.get(call.name, {}),
                self.parameter_models.get(call.name),
                self.today,
                self.request,
            ):
                continue
            required = {index for index in step.depende_de}
            pending = self.missing(executions)
            if not any(any(item.startswith(f"paso {index + 1}:") for item in pending) for index in required):
                return True
        return False

    async def execute(
        self,
        registry: ToolRegistry,
        calls: list[ToolCall],
        ctx: ToolContext,
        executions: list[ToolExecution],
        allowed_names: set[str],
    ) -> list[ToolExecution]:
        """Agrupa pasos independientes; conserva el orden de las respuestas al modelo."""
        if not self.steps:
            return await registry.execute_all(calls, ctx, allowed_names=allowed_names)
        remaining = list(enumerate(self._bind_export_call(call) for call in calls))
        completed: dict[int, ToolExecution] = {}
        evidence = list(executions)
        while remaining:
            ready = [(index, call) for index, call in remaining if self.ready(call, evidence)]
            if not ready:
                for index, call in remaining:
                    completed[index] = ToolExecution(
                        call,
                        ToolResult(
                            ToolStatus.INVALID_ARGUMENTS,
                            {
                                "mensaje": "Paso bloqueado: dependencias o filtros del plan no cumplidos. "
                                "Ejecuta una llamada por paso con sus argumentos declarados.",
                                "argumentos_del_plan": [
                                    step.argumentos.get(call.name, {})
                                    for step in self.steps
                                    if call.name in step.herramientas
                                ],
                                "campos_admitidos": sorted(self.parameter_models[call.name].model_fields)
                                if call.name in self.parameter_models
                                else [],
                                "correccion": "Elimina los campos que no figuren en el esquema. Conserva los filtros "
                                "del paso y usa una llamada por periodo.",
                            },
                        ),
                        0,
                        None,
                    )
                break
            results = await registry.execute_all([call for _, call in ready], ctx, allowed_names=allowed_names)
            for (index, _), result in zip(ready, results, strict=True):
                completed[index] = result
                evidence.append(result)
            remaining = [(index, call) for index, call in remaining if index not in completed]
        return [completed[index] for index in range(len(calls))]

    def _bind_export_call(self, call: ToolCall) -> ToolCall:
        """Complete omitted report options from a unique validated step; never bind writes."""
        model = self.parameter_models.get(call.name)
        if call.name not in {"generar_informe", "generar_informe_ejecutivo"} or model is None:
            return call
        try:
            actual = json.loads(call.arguments or "{}")
            if not isinstance(actual, dict):
                return call
            actual = normalize_arguments(model, actual, partial=True)
            candidates = [
                {**step.argumentos.get(call.name, {}), **actual}
                for step in self.steps
                if call.name in step.herramientas
                and all(
                    key not in actual or actual[key] == value
                    for key, value in step.argumentos.get(call.name, {}).items()
                )
            ]
            if len(candidates) != 1:
                return call
            bound = normalize_arguments(model, candidates[0], partial=False)
            return ToolCall(call.call_id, call.name, json.dumps(bound, ensure_ascii=False))
        except (ValueError, TypeError):
            return call

    def recovery_message(self, missing: list[str]) -> str:
        return (
            "VERIFICACIÓN DEL PLAN: "
            + json.dumps(missing, ensure_ascii=False)
            + (
                ". Revisa los resultados y corrige los pasos que puedas completar con las fuentes autorizadas. "
                "No inventes datos ni confirmes entregas pendientes. Si necesitas aclaración, pídela."
            )
        )


def recovery_tools(schemas: list[ToolSchema]) -> list[ToolSchema]:
    """La recuperación automática ofrece solo consultas conocidas y exportación local.

    Lista explícita conservadora: herramientas nuevas quedan fuera hasta revisar
    sus efectos. No hay envíos de correo ni operaciones de agenda en la lista.
    """
    safe = {
        PLAN_TOOL,
        "plantilla",
        "operar_resultado",
        "turnos_dia",
        "estadisticas_salariales",
        "ranking_salarial",
        "comparativa_salarial",
        "analisis_economico_nominas",
        "consulta_cruzada",
        "datos_de_personas",
        "cruzar_resultados",
        "cruce_vacaciones_turnos",
        "vacaciones",
        "turnos_persona",
        "generar_informe",
        "generar_informe_ejecutivo",
        "boletines_tt",
        "consulta_agenda",
        "correos_recientes",
        "detalle_reunion",
        "disponibilidad_agenda",
        # Resto de mia.modules.rrhh.analitica (todas de solo lectura, mismo perfil que
        # "plantilla"/"estadisticas_salariales" ya en esta lista): sin ellas, si el modelo no
        # llama a ninguna en la primera ronda para una pregunta claramente analítica
        # (planned=True), la recuperación nunca puede completarse, aunque sea la herramienta
        # obvia para la pregunta — incidencia real reproducida con "Analiza el departamento X".
        "ficha_departamento",
        "panel_rrhh",
        "comparar_departamentos",
        "cobertura_semanal",
        "analitica_vacaciones",
        "altas_empleados",
        "tendencia_ausencias",
        "ranking_absentismo",
        "proximos_jubilacion",
        "analizar_departamento",
        "tendencia_metrica",
        "comparar_universal",
        "distribucion_plantilla",
    }
    return [schema for schema in schemas if schema.name in safe]


def _matching_arguments(
    execution: ToolExecution,
    expected: dict[str, Any],
    model: type[BaseModel] | None = None,
    today: date | None = None,
    message: str = "",
) -> bool:
    if not expected:
        # Nada declarado que comprobar: el resto de esta función solo compara `actual` contra
        # `expected`, por lo que el resultado ya sería trivialmente True. Validar igualmente el
        # esquema COMPLETO de `actual` aquí (campos desconocidos incluidos) duplicaría, de forma
        # prematura y silenciosa, lo que la ejecución real de la herramienta ya hace — y lo
        # sustituiría por el mensaje genérico "paso bloqueado" en vez del error específico y
        # accionable del propio esquema (incidencia real: un paso de plan sin filtros declarados
        # bloqueaba la ejecución entera de generar_informe_ejecutivo por un campo adicional del
        # modelo ajeno al contrato, con generar_informe_ejecutivo listo para interpretarlo él
        # mismo desde el mensaje original).
        return True
    try:
        actual = json.loads(execution.call.arguments or "{}")
        if isinstance(actual, dict) and model is not None:
            actual = normalize_arguments(model, actual, partial=False)
            expected = normalize_arguments(model, expected, partial=True)
            canonicalize = getattr(model, "evidence_arguments", None)
            if callable(canonicalize):
                actual = canonicalize(actual, today or date.today(), message)
                expected = canonicalize(expected, today or date.today(), message)
    except (ValueError, TypeError):
        return False
    return isinstance(actual, dict) and all(key in actual and actual[key] == value for key, value in expected.items())
