"""Motor de conversación: un único flujo para todas las preguntas.

    mensaje → LLM (con herramientas tipadas) → ejecución determinista
            → LLM (respuesta estructurada: habla + estado del avatar + texto)

El estado vive en el servidor. La transacción de base de datos nunca se
mantiene abierta mientras se espera al LLM.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Literal
from zoneinfo import ZoneInfo

from mia.auth import UserContext
from mia.conversation import guard
from mia.conversation.events import (
    AvatarEvent,
    ProgressEvent,
    ResultEvent,
    SessionEvent,
    SpeechEvent,
    ToolEvent,
    TurnEvent,
    TurnResult,
)
from mia.conversation.orchestrator import select_modules
from mia.conversation.persona import AvatarState, Persona
from mia.conversation.speech import SpeechExtractor
from mia.conversation.tools import (
    LAST_CALL,
    ToolContext,
    ToolExecution,
    ToolRegistry,
    remember_last_call,
    remember_population,
    remember_table,
)
from mia.data import Database
from mia.data.repositories import AuditRepository, ConversationRepository
from mia.llm import (
    LLMCompleted,
    LLMError,
    LLMProvider,
    LLMRequest,
    Message,
    TextDelta,
    ToolCall,
    ToolCallRequested,
    WebSources,
)
from mia.diagnostics import EventStage, EventStatus, begin_trace, emit as diag_emit
from mia.observability import current_request_id, get_logger
from mia.presentation.intent import build_presentation_hint, classify_query
from mia.privacy_gateway.context_manager import set_operation_context
from mia.reporting.planner import planner
from mia.reporting.delivery import download_formats, merge_report_sources, resolve_export_request
from mia.reporting.comparisons import (
    LAST_PAYROLL_COMPARISON, explicit_month_comparison, is_export_followup, remembered_comparison,
)
from mia.rules import rules_for_prompt

log = get_logger(__name__)

MAX_MESSAGE_CHARS = 4000
NEUTRAL_SPEECH = "Te lo dejo en pantalla."
MAX_WEB_SOURCES = 12

@lru_cache(maxsize=1)
def _module_keywords() -> dict[str, tuple[str, ...]]:
    """Vocabulario de cada dominio real, para el orquestador (`select_modules`). `rrhh` (las 3
    herramientas de `sistema`) no necesita entrada: siempre se incluye por defecto. Reducir cuánto
    catálogo se ofrece por turno es el motivo de esto (82 herramientas → ~21.000 tokens siempre,
    confirmado por medición real); el diseño de `select_modules` hace que un vocabulario incompleto
    nunca rompa nada, solo deje de ahorrar en ese mensaje (cae al catálogo completo).

    Import diferido (no al nivel de módulo): cada dominio de ``mia.modules.rrhh`` importa de
    ``mia.conversation`` (Tool, ToolRegistry…) para definirse, así que importarlos aquí arriba, en
    un módulo que es parte de ``mia.conversation``, crearía un ciclo. Al llamarse ya con la app
    arrancada, ``mia.conversation`` está completamente inicializado y la importación es segura;
    ``lru_cache`` evita repetirla en cada turno.
    """
    from mia.modules.finanzas import KEYWORDS as finanzas
    from mia.modules.rrhh.analitica import KEYWORDS as analitica
    from mia.modules.rrhh.correo import KEYWORDS as correo
    from mia.modules.rrhh.curriculums import KEYWORDS as curriculums
    from mia.modules.rrhh.documentos import KEYWORDS as documentos
    from mia.modules.rrhh.empleados import KEYWORDS as empleados
    from mia.modules.rrhh.fichajes import KEYWORDS as fichajes
    from mia.modules.rrhh.informes import KEYWORDS as informes
    from mia.modules.rrhh.nominas import KEYWORDS as nominas
    from mia.modules.rrhh.trabajo_temporal import KEYWORDS as trabajo_temporal
    from mia.modules.rrhh.turnos import KEYWORDS as turnos
    from mia.modules.rrhh.vacaciones import KEYWORDS as vacaciones

    return {
        "finanzas": finanzas,
        "empleados": empleados,
        "turnos": turnos,
        "fichajes": fichajes,
        "vacaciones": vacaciones,
        "nominas": nominas,
        "documentos": documentos,
        "curriculums": curriculums,
        "trabajo_temporal": trabajo_temporal,
        "correo": correo,
        "analitica": analitica,
        "informes": informes,
    }


def _module_hint(selected: set[str]) -> str:
    """Si la pregunta suena a un módulo sin herramientas reales todavía, que lo diga con
    naturalidad en vez de inventar datos (ningún Tool de ese módulo llegaría a ofrecerse)."""
    if "finanzas" in selected:
        return (
            "\n\n## Pista para este mensaje\nLa pregunta parece de Finanzas, que todavía no "
            "está disponible (no hay fuente de datos conectada). Dilo con naturalidad, sin "
            "inventar cifras ni datos."
        )
    return ""


_REPORT_DOMAIN_HINTS: dict[str, str] = {
    "payroll": "coste salarial / importes de nómina (usa analisis_economico_nominas, NUNCA el informe "
    "ejecutivo genérico para esto)",
    "shift": "turnos / absentismo",
    "vacation": "saldos o solicitudes de vacaciones",
    "employee": "plantilla / datos de empleados",
    "timesheet": "trabajo temporal / horas",
    "document": "documentos firmados",
}


def _report_hint(message: str, user: UserContext, today: date) -> str:
    """Conexión general del ``ReportPlanner`` al pipeline conversacional (Bloque II, Fase F): una pista
    NO VINCULANTE (el modelo sigue decidiendo qué herramienta llamar) calculada con el MISMO planificador
    determinista ya validado — nunca un segundo planificador, nunca una decisión de permisos o
    k-anonimato basada en texto generado. Reduce la ambigüedad de qué herramienta usar para CUALQUIER
    dominio del catálogo semántico (nóminas, turnos, vacaciones, plantilla…), no solo el caso puntual ya
    resuelto con un guard explícito dentro de ``generar_informe_ejecutivo``. Si la petición no resuelve
    ningún campo conocido, no añade nada (sin ruido para preguntas normales)."""
    plan = planner.plan(message, user=user, today=today)
    if plan.is_empty:
        return ""
    domains = sorted(
        {m.field.domain for m in plan.granted_metrics} | {d.domain for d in plan.dimensions},
        key=lambda d: _REPORT_DOMAIN_HINTS.get(d, d),
    )
    described = [_REPORT_DOMAIN_HINTS.get(d) for d in domains if d in _REPORT_DOMAIN_HINTS]
    if not described:
        return ""
    period_note = f" Periodo detectado: {plan.period.label}." if plan.period else ""
    explicit_pair = explicit_month_comparison(message)
    payroll_request = any(m.field.domain == "payroll" for m in plan.metrics)
    if explicit_pair and payroll_request:
        compare_note = (
            f" Comparativa de nóminas entre {explicit_pair[0]} y {explicit_pair[1]}: "
            "llama a generar_informe (o generar_informe_ejecutivo) en el formato solicitado. "
            "El motor consulta y consolida ambos periodos automáticamente; NO necesitan "
            "estar activos a la vez en la sesión. No afirmes lo contrario."
        )
    else:
        compare_note = " Parece una comparativa entre periodos o grupos." if plan.compare else ""
    return (
        "\n\n## Pista de datos detectados\nEsta petición parece referirse a: "
        f"{'; '.join(described)}.{period_note}{compare_note} Usa la herramienta real que calcula ese "
        "dato — nunca sustituyas por un informe genérico de plantilla si el dato pedido no está en él."
    )


def _payroll_comparison_spec(message: str, user: UserContext, today: date) -> dict | None:
    periods = explicit_month_comparison(message)
    if periods is None:
        return None
    plan = planner.plan(message, user=user, today=today)
    field_names = sorted({m.field.name for m in plan.metrics if m.field.domain == "payroll"})
    if not field_names:
        return None
    # Solamente metadatos: el contexto NO persiste importes salariales.
    return {"periodos": list(periods), "campos": field_names}


@dataclass(slots=True)
class _TurnState:
    started: float
    session_id: str
    state: dict[str, Any]
    executions: list[ToolExecution] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"input": 0, "cached": 0, "output": 0})
    spoken: list[str] = field(default_factory=list)
    web_sources: list[dict[str, str]] = field(default_factory=list)

    def add_web_sources(self, sources: tuple[dict[str, str], ...]) -> None:
        known = {s["url"] for s in self.web_sources}
        self.web_sources += [s for s in sources if s["url"] not in known and len(self.web_sources) < MAX_WEB_SOURCES]

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)


@dataclass(frozen=True, slots=True)
class FinalAnswer:
    speech: str
    avatar_state: str
    text: str


def describe_focus(state: dict[str, Any]) -> str:
    """Resumen del foco para el prompt (lo fijan las herramientas con state_updates)."""
    lines = []
    person = state.get("foco_persona")
    if isinstance(person, dict) and person.get("empleado_id"):
        extra = f", {person['departamento']}" if person.get("departamento") else ""
        lines.append(f"- Persona: {person.get('nombre')} (empleado_id {person['empleado_id']}{extra})")
    if state.get("foco_departamento"):
        lines.append(f"- Departamento: {state['foco_departamento']}")
    population = state.get("ultima_poblacion")
    if isinstance(population, dict) and population.get("total") is not None:
        lines.append(
            f"- Último resultado con personas: {population.get('etiqueta')} ({population['total']}). "
            "Para «de esos/ellas», «quiénes son» o «cuántos son», usa sobre_resultado_anterior=true."
        )
    period = state.get("foco_periodo")
    if isinstance(period, dict) and period.get("desde"):
        lines.append(f"- Periodo: {period['desde']} a {period.get('hasta', period['desde'])}")
    last_call = state.get(LAST_CALL)
    if isinstance(last_call, dict) and last_call.get("herramienta"):
        params = ", ".join(f"{k}={v}" for k, v in (last_call.get("parametros") or {}).items())
        lines.append(
            f"- Última consulta: {last_call['herramienta']}({params}). Si la pregunta solo cambia "
            "un dato de esta (otro departamento, periodo, tipo…), repite esta misma consulta "
            "cambiando solo ese dato; no la repitas igual si la pregunta es otra cosa distinta."
        )
    return "\n".join(lines)


_CITATION = re.compile(r"\s*\(\s*\[[^\]]*\]\(https?://[^)]*\)\s*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://)[^)]*\)")
_FIELD = r'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"'


def _answer_fields(raw: str) -> dict[str, str] | None:
    """Campos habla/texto/estado_avatar de la respuesta del modelo.

    Con búsqueda web, el proveedor mete las citas con saltos de línea REALES dentro de las cadenas del JSON,
    que el JSON estricto rechaza (fallo real: se mostraba el JSON en bruto). Se prueba el modo tolerante y,
    como último recurso, se extrae cada campo por separado.
    """
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 < end:
        try:
            data = json.loads(text[start : end + 1], strict=False)
            if isinstance(data, dict):
                return {k: str(v or "") for k, v in data.items()}
        except json.JSONDecodeError:
            pass
    found = {}
    for key in ("habla", "estado_avatar", "texto"):
        if match := re.search(_FIELD.format(key=key), text, re.DOTALL):
            try:
                found[key] = json.loads(f'"{match.group(1)}"', strict=False)
            except json.JSONDecodeError:
                found[key] = match.group(1)
    return found or None


def parse_final_answer(raw: str) -> FinalAnswer:
    fields = _answer_fields(raw)
    if fields is not None:
        speech = fields.get("habla", "").strip()
        text = fields.get("texto", "").strip() or speech
        state = fields.get("estado_avatar", "")
    else:
        text = raw.strip()
        # Sin JSON legible: nunca se locuta el texto en bruto (podría ser el propio JSON roto).
        speech = NEUTRAL_SPEECH if text.startswith("{") else text.split(". ")[0][:250]
        state = ""
    # Las citas «([sitio](url))» las muestra la pantalla como fuentes: fuera del texto y de la voz.
    text = _CITATION.sub("", text).strip()
    speech = _MD_LINK.sub(r"\1", _CITATION.sub("", speech)).strip()
    if state not in AvatarState.__members__.values():
        state = AvatarState.HABLANDO.value
    cleaned_speech, text = guard.clean_speech(speech), guard.clean(text)
    if not cleaned_speech:
        # Nunca se recurre al texto escrito para la voz: puede contener importes u otros datos
        # que la salvaguarda acaba de retirar (fallo real: «cobró 1.344,59 €» acabó en la voz).
        cleaned_speech = NEUTRAL_SPEECH if speech else guard.clean_speech(text)
    return FinalAnswer(speech=cleaned_speech, avatar_state=state, text=text or cleaned_speech)


class ConversationEngine:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        tools: ToolRegistry,
        db: Database,
        persona: Persona | None = None,
        timezone: str = "Europe/Madrid",
        history_turns: int = 12,
        max_tool_rounds: int = 4,
        max_output_tokens: int = 1200,
        max_report_rows: int = 5000,
        mailbox_for: Callable[[UserContext], str | None] | None = None,
        turn_budget_seconds: float = 75.0,
    ) -> None:
        self._turn_budget = turn_budget_seconds
        self._mailbox_for = mailbox_for
        self._max_report_rows = max_report_rows
        self._llm = llm
        self._tools = tools
        self._db = db
        self.persona = persona or Persona()
        self._tz = ZoneInfo(timezone)
        self._history_turns = history_turns
        self._max_tool_rounds = max_tool_rounds
        self._max_output_tokens = max_output_tokens

    async def run(
        self,
        *,
        message: str,
        user: UserContext,
        session_id: str | None,
        attachment_ids: list[str] | None = None,
        attachment_service: Any | None = None,
    ) -> AsyncIterator[TurnEvent]:
        message = message.strip()[:MAX_MESSAGE_CHARS]
        request_id = current_request_id()
        set_operation_context(user_id=user.user_id, operation_id=request_id or uuid.uuid4().hex)

        async with begin_trace(
            query=message,
            user_id=user.user_id,
            user_name=user.display_name,
            session_id=session_id,
            request_id=request_id,
        ) as trace:
            diag_emit(EventStage.REQUEST_RECEIVED, data={"query": message, "session_id": session_id})

            # 1) Transacción corta: sesión, historial y turno del usuario.
            async with self._db.session() as db:
                repo = ConversationRepository(db)
                session = await repo.get_or_create(session_id, user.user_id)
                history = await repo.recent_turns(session.id, self._history_turns)
                await repo.add_turn(session_id=session.id, request_id=request_id, role="user", content=message)
                turn = _TurnState(time.perf_counter(), session.id, dict(session.state or {}))

            # Un usuario puede analizar los dos ejercicios y solicitar el PDF en el turno siguiente.
            # Recuperar únicamente la última intención comparativa explícita (sin importes), nunca
            # depender de que ambos resultados estén «activos» en el buffer de una sola tabla.
            local_today = datetime.now(self._tz).date()
            current_plan = planner.plan(message, user=user, today=local_today)
            competing_domain = any(m.field.domain != "payroll" for m in current_plan.metrics)
            if competing_domain or (current_plan.period and not explicit_month_comparison(message)):
                turn.state.pop(LAST_PAYROLL_COMPARISON, None)
            latest = _payroll_comparison_spec(message, user, local_today)
            if latest is not None:
                turn.state[LAST_PAYROLL_COMPARISON] = latest
            elif is_export_followup(message) and not competing_domain and LAST_PAYROLL_COMPARISON not in turn.state:
                for previous in reversed(history):
                    if previous.role != "user":
                        continue
                    if is_export_followup(previous.content):
                        continue
                    latest = _payroll_comparison_spec(previous.content, user, local_today)
                    if latest is not None:
                        turn.state[LAST_PAYROLL_COMPARISON] = latest
                    break

            diag_emit(EventStage.USER_CONTEXT, data={
                "user_id": user.user_id,
                "display_name": user.display_name,
                "permissions": list(user.permissions),
            })
            diag_emit(EventStage.CONVERSATION_CONTEXT, data={
                "session_id": turn.session_id,
                "history_turns": len(history),
                "session_state_keys": list(turn.state.keys()),
            })

            yield SessionEvent(session_id=turn.session_id)
            yield AvatarEvent(state=AvatarState.PENSANDO.value)

            messages = [
                Message(role="user" if t.role == "user" else "assistant", content=t.content)
                for t in history
                if t.role in {"user", "assistant"}
            ]
            messages.append(Message(role="user", content=message))
            now = datetime.now(self._tz)
            if trace is not None:
                trace.record.now_local = now.isoformat()
            mailbox = self._mailbox_for(user) or "" if self._mailbox_for else ""
            selected_modules = select_modules(message, _module_keywords())
            qa = classify_query(message)

            diag_emit(EventStage.DOMAIN_DETECTION, data={"modules": list(selected_modules)})
            diag_emit(
                EventStage.PRESENTATION_INTENT_CLASSIFIED,
                data={
                    "intent": qa.presentation_intent.value,
                    "depth": qa.response_depth.value,
                    "comparison_requested": qa.comparison_requested,
                    "analytics_requested": qa.analytics_requested,
                    "temporal_scope": qa.temporal_scope,
                },
            )

            diag_emit(EventStage.PROMPT_BUILD_START)
            system = self.persona.system_prompt(
                business_rules=rules_for_prompt(), capabilities=self._tools.capabilities_for(user)
            )
            _pres_hint = build_presentation_hint(qa)
            context = self.persona.turn_context(
                user_name=user.display_name,
                now=now,
                mailbox=mailbox,
                focus=describe_focus(turn.state),
                hint=(
                    self.persona.hint_for(message, mailbox)
                    + _module_hint(selected_modules)
                    + _report_hint(message, user, now.date())
                    + ("\n\n## Continuación de comparativa salarial\n"
                       "El usuario pide exportar la comparativa previa de nóminas. Ejecuta "
                       "generar_informe: recuperará los dos periodos de la petición anterior y "
                       "consultará ambas fuentes sin que deban estar simultáneamente activas."
                       if remembered_comparison(turn.state, message) else "")
                    + ("\n" + _pres_hint if _pres_hint else "")
                ).strip(),
            )
            # Adjuntos: procesar IDs recibidos y actualizar session state
            attachment_context = ""
            if attachment_ids and attachment_service is not None:
                from mia.attachments.model import AttachmentRef, get_active_refs, merge_refs, set_active_refs  # noqa: PLC0415
                new_refs: list[AttachmentRef] = []
                ctx_parts: list[str] = []
                for aid in attachment_ids[:10]:
                    record = attachment_service.get_for_user(aid, user.user_id)
                    if record is not None:
                        new_refs.append(attachment_service.to_ref(record))
                        ctx_parts.append(attachment_service.build_context(aid, user.user_id))
                if ctx_parts:
                    existing = get_active_refs(turn.state)
                    set_active_refs(turn.state, merge_refs(existing, new_refs))
                    attachment_context = "\n\n## Archivos adjuntos en este mensaje\n" + "\n\n".join(ctx_parts)
                    diag_emit(EventStage.ATTACHMENT_CONTEXT_INJECTED, data={
                        "count": len(ctx_parts),
                        "ids": attachment_ids[:10],
                    })

            messages[-1] = Message(role="user", content=message + context + attachment_context)
            diag_emit(EventStage.PROMPT_BUILD_COMPLETE, data={
                "system_chars": len(system),
                "context_chars": len(context),
                "attachment_context_chars": len(attachment_context),
                "total_history_messages": len(messages),
            })

            ctx = ToolContext(
                user=user,
                request_id=request_id,
                now=now,
                session_state=turn.state,
                user_message=message,
                attachment_service=attachment_service,
            )

            # Si se solicitan archivos, posponer cualquier afirmación hablada
            # del LLM hasta comprobar que existen descargas reales.
            export_request = resolve_export_request(message, history)
            status: Literal["ok", "error"] = "ok"
            try:
                final: FinalAnswer | None = None
                async for event in self._reason(system, messages, ctx, turn, modules=selected_modules):
                    if isinstance(event, FinalAnswer):
                        final = event
                    elif export_request and isinstance(event, SpeechEvent) and not event.filler:
                        # El LLM podría decir "ya está creado" antes de que
                        # el backend haya persistido nada.
                        continue
                    else:
                        yield event
                assert final is not None  # noqa: S101
            except LLMError as exc:
                log.error("conversation.llm_failed", error=str(exc))
                diag_emit(EventStage.LLM_ERROR, status=EventStatus.ERROR, data={"error": str(exc)})
                status = "error"
                final = FinalAnswer(self.persona.error_phrase, AvatarState.CONFUNDIDA.value, self.persona.error_phrase)
                yield SpeechEvent(text=final.speech)

            # Contrato de entrega: el texto del LLM NUNCA demuestra que existan
            # archivos. Si se pidieron varios formatos, intentar exportarlos desde
            # los mismos resultados y exigir una presentación download por formato.
            if export_request:
                original_request, formats = export_request
                verified = download_formats(turn.executions)
                missing = [fmt for fmt in formats if fmt not in verified]
                if missing:
                    # Varias tablas por departamento se guardaban separadas; la
                    # última pisaba las anteriores. Consolidar las de la MISMA
                    # herramienta con sus etiquetas antes de exportar.
                    merged = merge_report_sources(
                        turn.executions, title=original_request,
                    )
                    if merged is not None:
                        source = next(e.call.name for e in turn.executions
                                      if e.result.presentation and
                                      e.result.presentation.get("type") in {"table", "dashboard"})
                        remember_table(turn.state, merged, self._max_report_rows,
                                       source_tool=source)
                    can_export = bool(merged) or (
                        message != original_request and bool(turn.state.get("ultima_presentacion"))
                    )
                    if can_export:
                        export_ctx = replace(ctx, user_message=original_request)
                        for fmt in missing:
                            execution = await self._tools.execute(
                                ToolCall(f"delivery:{uuid.uuid4().hex}", "generar_informe",
                                         json.dumps({"formato": fmt}, ensure_ascii=False)),
                                export_ctx,
                            )
                            turn.executions.append(execution)
                            yield ToolEvent(
                                name=execution.call.name,
                                status=execution.result.status.value,
                                elapsed_ms=execution.elapsed_ms,
                            )
                verified = download_formats(turn.executions)
                successes = [(fmt, verified[fmt]) for fmt in formats if fmt in verified]
                missing = [fmt for fmt in formats if fmt not in verified]
                labels = {"pdf": "PDF", "pptx": "PowerPoint", "xlsx": "Excel"}
                lines = [
                    f"- [{labels[fmt]}]({presentation['url']})"
                    for fmt, presentation in successes
                ]
                if missing:
                    lines.append(
                        "No se han generado: " + ", ".join(labels[f] for f in missing)
                        + ". No se confirma una entrega que no existe."
                    )
                    failures = [
                        str(e.result.summary.get("mensaje", ""))[:220]
                        for e in turn.executions
                        if e.call.name == "generar_informe"
                        and e.result.status.value != "ok"
                        and isinstance(e.result.summary, dict)
                    ]
                    if failures:
                        lines.append("Motivo comunicado por el motor: " + failures[-1])
                    elif not successes:
                        lines.append(
                            "No hay datos verificables y completos para exportar desde esta ejecución."
                        )
                else:
                    lines.insert(0, "Archivos generados y disponibles para descargar:")
                confirmed = "\n".join(lines)
                spoken = (
                    "Los archivos solicitados están generados y disponibles para descargar."
                    if not missing else
                    "No se han podido entregar todos los documentos solicitados. Consulta el detalle en pantalla."
                )
                final = FinalAnswer(spoken, final.avatar_state, confirmed)
                if missing and not successes:
                    status = "error"
                yield SpeechEvent(text=spoken)

            yield AvatarEvent(state=final.avatar_state)
            result = TurnResult(
                session_id=turn.session_id,
                status=status,
                answer=final.text,
                speech=final.speech,
                avatar_state=final.avatar_state,
                presentations=[e.result.presentation for e in turn.executions if e.result.presentation],
                web_sources=turn.web_sources,
                summaries=[
                    {"tool": e.call.name, "summary": e.result.summary}
                    for e in turn.executions
                    if e.result.status.value == "ok" and isinstance(e.result.summary, dict)
                ],
                tools=[
                    {"name": e.call.name, "status": e.result.status.value, "elapsed_ms": e.elapsed_ms}
                    for e in turn.executions
                ],
                elapsed_ms=turn.elapsed_ms(),
                usage=turn.usage,
                presentation_intent=qa.presentation_intent.value,
            )

            # 2) Transacción corta: respuesta, estado y auditoría.
            async with self._db.session() as db:
                repo = ConversationRepository(db)
                session = await repo.get_or_create(turn.session_id, user.user_id)
                session.state = turn.state
                await repo.add_turn(
                    session_id=turn.session_id,
                    request_id=request_id,
                    role="assistant",
                    content=result.answer,
                    speech=result.speech,
                    avatar_state=result.avatar_state,
                    tool_calls=result.tools,
                    presentation={"items": result.presentations},
                    latency_ms=result.elapsed_ms,
                )
                audit = AuditRepository(db)
                for execution in turn.executions:
                    if execution.audit_resource:
                        await audit.record(
                            user_id=user.user_id,
                            action=f"tool:{execution.call.name}",
                            resource=execution.audit_resource,
                            outcome=execution.result.status.value,
                            request_id=request_id,
                            detail={"arguments": json.loads(execution.call.arguments or "{}")},
                        )

            diag_emit(EventStage.RESPONSE_SENT, status=EventStatus.SUCCESS, data={
                "status": status,
                "elapsed_ms": result.elapsed_ms,
                "tools_called": len(result.tools),
                "tokens": result.usage,
                "presentations": [p.get("type") for p in result.presentations if isinstance(p, dict) and p.get("type")],
            })
            if trace is not None:
                trace.finish(
                    answer=final.text,
                    status=status,
                    llm_model=self._llm.__class__.__name__,
                )

            log.info(
                "conversation.turn",
                session_id=turn.session_id,
                status=status,
                elapsed_ms=result.elapsed_ms,
                tools=[t["name"] for t in result.tools],
                **{f"tokens_{k}": v for k, v in turn.usage.items()},
            )
            yield ResultEvent(result=result)

    @staticmethod
    def _speak(sentences: list[str], turn: _TurnState) -> list[TurnEvent]:
        """Convierte frases en eventos de voz, descartando las que la salvaguarda bloquea."""
        events: list[TurnEvent] = []
        for sentence in sentences:
            if guard.speech_blocked(sentence):
                continue
            if not turn.spoken:
                events.append(AvatarEvent(state=AvatarState.HABLANDO.value))
            turn.spoken.append(sentence)
            events.append(SpeechEvent(text=sentence))
        return events

    async def _reason(
        self, system: str, messages: list[Message], ctx: ToolContext, turn: _TurnState, *, modules: set[str]
    ) -> AsyncIterator[TurnEvent | FinalAnswer]:
        tools = self._tools.schemas_for(ctx.user, modules=modules)
        diag_emit(EventStage.TOOL_SELECTION, data={"available": [t.name for t in tools]})
        filler_sent = False
        for round_index in range(self._max_tool_rounds + 1):
            over_budget = (time.perf_counter() - turn.started) > self._turn_budget
            allow_tools = bool(tools) and round_index < self._max_tool_rounds and not over_budget
            if over_budget and round_index:
                log.warning("conversation.turn_budget_exceeded", elapsed_s=round(time.perf_counter() - turn.started, 1))
                diag_emit(EventStage.WARNING, data={"reason": "turn_budget_exceeded", "elapsed_s": round(time.perf_counter() - turn.started, 1)})
            request = LLMRequest(
                system=system,
                messages=messages,
                tools=tools if allow_tools else [],
                response_schema=self.persona.response_schema(),
                max_output_tokens=self._max_output_tokens,
            )
            extractor = SpeechExtractor()
            raw: list[str] = []
            calls: list[ToolCall] = []
            llm_started = time.perf_counter()
            first_token = False
            diag_emit(EventStage.LLM_REQUEST, data={"round": round_index, "tools_offered": len(tools) if allow_tools else 0})
            async for event in self._llm.stream(request):
                if isinstance(event, TextDelta):
                    if not first_token:
                        first_token = True
                        diag_emit(EventStage.LLM_FIRST_TOKEN, duration_ms=int((time.perf_counter() - llm_started) * 1000))
                    raw.append(event.text)
                    for speech_event in self._speak(extractor.feed(event.text), turn):
                        yield speech_event
                elif isinstance(event, ToolCallRequested):
                    calls.append(event.call)
                elif isinstance(event, WebSources):
                    turn.add_web_sources(event.sources)
                elif isinstance(event, LLMCompleted):
                    turn.usage["input"] += event.input_tokens
                    turn.usage["cached"] += event.cached_tokens
                    turn.usage["output"] += event.output_tokens
                    diag_emit(
                        EventStage.LLM_RESPONSE,
                        status=EventStatus.SUCCESS,
                        duration_ms=int((time.perf_counter() - llm_started) * 1000),
                        data={
                            "round": round_index,
                            "input_tokens": event.input_tokens,
                            "output_tokens": event.output_tokens,
                            "cached_tokens": event.cached_tokens,
                            "tool_calls_requested": len(calls),
                        },
                    )

            if not calls:
                for speech_event in self._speak(extractor.finish(), turn):
                    yield speech_event
                yield parse_final_answer("".join(raw))
                return

            if not filler_sent:
                filler_sent = True
                yield AvatarEvent(state=AvatarState.CONCENTRADA.value)
                yield SpeechEvent(text=self.persona.next_waiting_phrase(), filler=True)
            yield ProgressEvent(stage="tools", message="Consultando " + ", ".join(c.name for c in calls))

            # Las exportaciones consumen una presentación producida por otra herramienta.
            # Si GPT solicita ambas en la misma ronda, ejecutar primero las fuentes y
            # guardar sus resultados en la sesión ANTES de llamar al exportador.
            # No se cambia el orden de las respuestas al LLM ni sus call_id.
            report_names = {"generar_informe", "generar_informe_ejecutivo"}
            sources = [c for c in calls if c.name not in report_names]
            exports = [c for c in calls if c.name in report_names]
            if sources and exports:
                source_execs = await self._tools.execute_all(sources, ctx)
                for source_exec in source_execs:
                    turn.state.update(source_exec.result.state_updates)
                    remember_table(
                        turn.state, source_exec.result.presentation, self._max_report_rows,
                        source_exec.result.summary, source_tool=source_exec.call.name,
                    )
                # Un exportador puede depender del resultado del informe autónomo
                # anterior. Evitar también concurrencia entre exportadores.
                export_execs = []
                for export_call in exports:
                    export_exec = await self._tools.execute(export_call, ctx)
                    export_execs.append(export_exec)
                    turn.state.update(export_exec.result.state_updates)
                by_id = {e.call.call_id: e for e in (*source_execs, *export_execs)}
                executions = [by_id[c.call_id] for c in calls]
            else:
                executions = await self._tools.execute_all(calls, ctx)
            turn.executions.extend(executions)
            messages.append(Message(role="assistant", content="".join(raw), tool_calls=tuple(calls)))
            for execution in executions:
                turn.state.update(execution.result.state_updates)
                remember_table(
                    turn.state,
                    execution.result.presentation,
                    self._max_report_rows,
                    execution.result.summary,
                    source_tool=execution.call.name,
                )
                remember_population(turn.state, execution.result.state_updates.get("ultima_poblacion"))
                remember_last_call(turn.state, execution)
                messages.append(
                    Message(role="tool", content=execution.as_llm_output(), tool_call_id=execution.call.call_id)
                )
                yield ToolEvent(
                    name=execution.call.name,
                    status=execution.result.status.value,
                    elapsed_ms=execution.elapsed_ms,
                )
        raise LLMError("Se superó el número máximo de rondas de herramientas")  # pragma: no cover

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    async def complete(
        self,
        *,
        message: str,
        user: UserContext,
        session_id: str | None,
        attachment_ids: list[str] | None = None,
        attachment_service: Any | None = None,
    ) -> TurnResult:
        """Ejecuta el turno completo y devuelve solo el resultado final."""
        async for event in self.run(
            message=message,
            user=user,
            session_id=session_id,
            attachment_ids=attachment_ids,
            attachment_service=attachment_service,
        ):
            if isinstance(event, ResultEvent):
                return event.result
        raise RuntimeError("El turno terminó sin resultado")  # pragma: no cover
