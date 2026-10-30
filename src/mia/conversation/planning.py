"""Plan explícito del turno y comprobación de evidencia, sin conceder permisos.

El modelo propone pasos; solo ejecuciones reales satisfacen sus requisitos.
El contrato de formatos procede de la petición y no puede reducirlo el plan.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, model_validator

from mia.conversation.tools import Tool, ToolContext, ToolExecution, ToolRegistry, ToolResult, ToolStatus
from mia.llm import ToolCall, ToolSchema
from mia.reporting.delivery import download_formats, requested_formats
from mia.text import normalize_key

PLAN_TOOL = "planificar_tarea"


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

    def tool(self) -> Tool:
        async def propose(params: TaskSteps, ctx: ToolContext) -> ToolResult:
            unknown = {name for step in params.pasos for name in step.herramientas} - self.available
            if unknown or any(PLAN_TOOL in step.herramientas for step in params.pasos):
                return ToolResult(
                    ToolStatus.INVALID_ARGUMENTS,
                    {"mensaje": "El plan contiene herramientas no disponibles para este usuario."},
                )
            if self.revisions >= 2:
                return ToolResult(
                    ToolStatus.INVALID_ARGUMENTS, {"mensaje": "Se ha alcanzado el límite de replanteamiento."}
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
                    new = revised[old.objetivo].argumentos.get(name, {})
                    if any(key not in new or new[key] != value for key, value in constraints.items()):
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
            "Catálogo autorizado de nombres para planificar: " + ", ".join(sorted(self.available)) + ". "
            "Si un nombre no estaba ofrecido inicialmente, su esquema se ofrecerá al aceptar el plan.",
            TaskSteps,
            propose,
            available_names=tuple(sorted(self.available)),
        )

    def instructions(self) -> str:
        return (
            "\nPLAN DE EJECUCIÓN DEL TURNO: 1) obtener evidencia de las fuentes autorizadas; "
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
        missing: list[str] = []
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
                        and _matching_arguments(execution, step.argumentos.get(name, {}))
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

    def ready(self, call: ToolCall, executions: list[ToolExecution]) -> bool:
        """Un paso declarado solo se ejecuta tras sus dependencias y con sus filtros."""
        matching = [step for step in self.steps if call.name in step.herramientas]
        if not matching:
            return True  # consultas auxiliares mantienen los permisos del registro
        probe = ToolExecution(call, ToolResult.ok({}), 0, None)
        for step in matching:
            if not _matching_arguments(probe, step.argumentos.get(call.name, {})):
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
        remaining = list(enumerate(calls))
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
                            "Paso bloqueado: dependencias o filtros del plan no cumplidos.",
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
        "turnos_dia",
        "estadisticas_salariales",
        "ranking_salarial",
        "analisis_economico_nominas",
        "consulta_cruzada",
        "datos_de_personas",
        "generar_informe",
        "generar_informe_ejecutivo",
        "boletines_tt",
        "consulta_agenda",
        "detalle_reunion",
        "disponibilidad_agenda",
    }
    return [schema for schema in schemas if schema.name in safe]


def _matching_arguments(execution: ToolExecution, expected: dict[str, Any]) -> bool:
    try:
        actual = json.loads(execution.call.arguments or "{}")
    except (ValueError, TypeError):
        return False
    return isinstance(actual, dict) and all(key in actual and actual[key] == value for key, value in expected.items())
