"""Motor de conversación: un único flujo para todas las preguntas.

    mensaje → LLM (con herramientas tipadas) → ejecución determinista
            → LLM (respuesta estructurada: habla + estado del avatar + texto)

El estado vive en el servidor. La transacción de base de datos nunca se
mantiene abierta mientras se espera al LLM.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
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
from mia.conversation.persona import AvatarState, Persona
from mia.conversation.speech import SpeechExtractor
from mia.conversation.tools import ToolContext, ToolExecution, ToolRegistry
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
)
from mia.observability import current_request_id, get_logger
from mia.rules import rules_for_prompt

log = get_logger(__name__)

MAX_MESSAGE_CHARS = 4000


@dataclass(slots=True)
class _TurnState:
    started: float
    session_id: str
    state: dict[str, Any]
    executions: list[ToolExecution] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"input": 0, "cached": 0, "output": 0})
    spoken: list[str] = field(default_factory=list)

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
    period = state.get("foco_periodo")
    if isinstance(period, dict) and period.get("desde"):
        lines.append(f"- Periodo: {period['desde']} a {period.get('hasta', period['desde'])}")
    return "\n".join(lines)


def parse_final_answer(raw: str) -> FinalAnswer:
    try:
        data = json.loads(raw)
        speech = str(data.get("habla") or "").strip()
        text = str(data.get("texto") or "").strip() or speech
        state = str(data.get("estado_avatar") or "")
    except (json.JSONDecodeError, AttributeError):
        text = raw.strip()
        speech = text.split(". ")[0][:250]
        state = ""
    if state not in AvatarState.__members__.values():
        state = AvatarState.HABLANDO.value
    speech, text = guard.clean(speech), guard.clean(text)
    return FinalAnswer(speech=speech or text, avatar_state=state, text=text or speech)


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
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._db = db
        self.persona = persona or Persona()
        self._tz = ZoneInfo(timezone)
        self._history_turns = history_turns
        self._max_tool_rounds = max_tool_rounds
        self._max_output_tokens = max_output_tokens

    async def run(
        self, *, message: str, user: UserContext, session_id: str | None
    ) -> AsyncIterator[TurnEvent]:
        message = message.strip()[:MAX_MESSAGE_CHARS]
        request_id = current_request_id()

        # 1) Transacción corta: sesión, historial y turno del usuario.
        async with self._db.session() as db:
            repo = ConversationRepository(db)
            session = await repo.get_or_create(session_id, user.user_id)
            history = await repo.recent_turns(session.id, self._history_turns)
            await repo.add_turn(session_id=session.id, request_id=request_id, role="user", content=message)
            turn = _TurnState(time.perf_counter(), session.id, dict(session.state or {}))

        yield SessionEvent(session_id=turn.session_id)
        yield AvatarEvent(state=AvatarState.PENSANDO.value)

        messages = [
            Message(role="user" if t.role == "user" else "assistant", content=t.content)
            for t in history
            if t.role in {"user", "assistant"}
        ]
        messages.append(Message(role="user", content=message))
        now = datetime.now(self._tz)
        system = self.persona.system_prompt(
            user_name=user.display_name,
            now=now,
            business_rules=rules_for_prompt(),
            capabilities=self._tools.capabilities_for(user),
            focus=describe_focus(turn.state),
        )
        ctx = ToolContext(user=user, request_id=request_id, now=now, session_state=turn.state)

        status: Literal["ok", "error"] = "ok"
        try:
            final: FinalAnswer | None = None
            async for event in self._reason(system, messages, ctx, turn):
                if isinstance(event, FinalAnswer):
                    final = event
                else:
                    yield event
            assert final is not None  # noqa: S101
        except LLMError as exc:
            log.error("conversation.llm_failed", error=str(exc))
            status = "error"
            final = FinalAnswer(
                self.persona.error_phrase, AvatarState.CONFUNDIDA.value, self.persona.error_phrase
            )
            yield SpeechEvent(text=final.speech)

        yield AvatarEvent(state=final.avatar_state)
        result = TurnResult(
            session_id=turn.session_id,
            status=status,
            answer=final.text,
            speech=final.speech,
            avatar_state=final.avatar_state,
            presentations=[e.result.presentation for e in turn.executions if e.result.presentation],
            tools=[
                {"name": e.call.name, "status": e.result.status.value, "elapsed_ms": e.elapsed_ms}
                for e in turn.executions
            ],
            elapsed_ms=turn.elapsed_ms(),
            usage=turn.usage,
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
            if guard.is_blocked(sentence):
                continue
            if not turn.spoken:
                events.append(AvatarEvent(state=AvatarState.HABLANDO.value))
            turn.spoken.append(sentence)
            events.append(SpeechEvent(text=sentence))
        return events

    async def _reason(
        self, system: str, messages: list[Message], ctx: ToolContext, turn: _TurnState
    ) -> AsyncIterator[TurnEvent | FinalAnswer]:
        tools = self._tools.schemas_for(ctx.user)
        filler_sent = False
        for round_index in range(self._max_tool_rounds + 1):
            allow_tools = bool(tools) and round_index < self._max_tool_rounds
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
            async for event in self._llm.stream(request):
                if isinstance(event, TextDelta):
                    raw.append(event.text)
                    for speech_event in self._speak(extractor.feed(event.text), turn):
                        yield speech_event
                elif isinstance(event, ToolCallRequested):
                    calls.append(event.call)
                elif isinstance(event, LLMCompleted):
                    turn.usage["input"] += event.input_tokens
                    turn.usage["cached"] += event.cached_tokens
                    turn.usage["output"] += event.output_tokens

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

            executions = await self._tools.execute_all(calls, ctx)
            turn.executions.extend(executions)
            messages.append(Message(role="assistant", content="".join(raw), tool_calls=tuple(calls)))
            for execution in executions:
                turn.state.update(execution.result.state_updates)
                messages.append(
                    Message(
                        role="tool", content=execution.as_llm_output(), tool_call_id=execution.call.call_id
                    )
                )
                yield ToolEvent(
                    name=execution.call.name,
                    status=execution.result.status.value,
                    elapsed_ms=execution.elapsed_ms,
                )
        raise LLMError("Se superó el número máximo de rondas de herramientas")  # pragma: no cover

    async def complete(self, *, message: str, user: UserContext, session_id: str | None) -> TurnResult:
        """Ejecuta el turno completo y devuelve solo el resultado final."""
        async for event in self.run(message=message, user=user, session_id=session_id):
            if isinstance(event, ResultEvent):
                return event.result
        raise RuntimeError("El turno terminó sin resultado")  # pragma: no cover
