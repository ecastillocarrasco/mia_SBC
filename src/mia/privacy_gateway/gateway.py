"""Punto único de salida protegido hacia el proveedor LLM.

``PrivacyGateway`` implementa el mismo contrato que cualquier ``LLMProvider`` (ver mia.llm.base), así
que el resto de mIA no distingue si está hablando con OpenAI directamente o con el gateway: la única
forma de obtener un ``LLMProvider`` es ``mia.llm.factory.build_llm_provider()``, que SIEMPRE devuelve
una instancia envuelta en este gateway. Ningún módulo puede "olvidarse" de protegerse porque ningún
módulo tiene otra forma de llegar al proveedor real.

Con ``settings.enabled=False`` el envoltorio sigue existiendo (la arquitectura no tiene bypass), pero
se limita a reenviar sin coste — así el despliegue inicial no cambia ningún comportamiento existente
hasta validar la protección real por etapas.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import replace

from mia.llm.base import LLMEvent, LLMProvider, LLMRequest, TextDelta
from mia.privacy_gateway import audit
from mia.privacy_gateway.context_manager import current_operation
from mia.privacy_gateway.economic_minimization import redact_individual_amounts
from mia.privacy_gateway.exceptions import UnsafeContentBlockedError
from mia.privacy_gateway.inbound_inspector import sanitize_inbound
from mia.privacy_gateway.outbound_inspector import redact_secrets
from mia.privacy_gateway.policy_engine import Action, Policy, action_for, resolve_policy, score_threshold
from mia.privacy_gateway.presidio_engine import PresidioEngine, drop_overlapping, get_presidio_engine
from mia.privacy_gateway.prompt_injection_guard import scan as scan_injection
from mia.privacy_gateway.prompt_injection_guard import wrap_untrusted
from mia.privacy_gateway.token_vault import TokenVault
from mia.privacy_gateway.tokenizer import Tokenizer
from mia.settings import PrivacyGatewaySettings

_OPEN_BRACKET = "["
_MAX_PENDING_TOKEN_CHARS = 40
"""Longitud máxima de un «[TIPO_NNN]» con margen: pasado esto, un «[» abierto sin cerrar no merece
seguir reteniéndose esperando el cierre (no es un token, es texto normal con un corchete)."""


class _StreamBuffer:
    """Retiene la cola de cada fragmento de streaming mientras podría ser el principio de un pseudo-token
    partido entre dos TextDelta consecutivos (ver sección 9.1: «gestionar tokens divididos»)."""

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, chunk: str) -> str:
        combined = self._pending + chunk
        last_open = combined.rfind(_OPEN_BRACKET)
        cut = len(combined)
        still_open = last_open != -1 and "]" not in combined[last_open:]
        if still_open and len(combined) - last_open <= _MAX_PENDING_TOKEN_CHARS:
            cut = last_open
        self._pending = combined[cut:]
        return combined[:cut]

    def flush(self) -> str:
        out, self._pending = self._pending, ""
        return out


class PrivacyGateway(LLMProvider):
    def __init__(
        self, inner: LLMProvider, settings: PrivacyGatewaySettings, *, provider_name: str, model: str
    ) -> None:
        self._inner = inner
        self._settings = settings
        self._provider_name = provider_name
        self._model = model
        self._tokenizer: Tokenizer | None = None
        self._engine: PresidioEngine | None = None
        if settings.enabled:
            self._engine = get_presidio_engine(settings.spacy_model)
            vault = TokenVault(settings.vault_key.get_secret_value(), settings.vault_ttl_seconds)
            self._tokenizer = Tokenizer(self._engine, vault, ttl_seconds=float(settings.vault_ttl_seconds))

    def _identity(self) -> tuple[str, str]:
        op = current_operation()
        if op is None:
            return "unknown", "unscoped"
        return op.user_id, op.operation_id

    def _sanitize_request(
        self, request: LLMRequest, *, policy: Policy, user_id: str, operation_id: str
    ) -> LLMRequest:
        detected: Counter[str] = Counter()
        secrets_redacted = 0
        injection_hits = 0

        def _process(text: str, *, untrusted: bool = False) -> str:
            nonlocal secrets_redacted, injection_hits
            if not text:
                return text
            if untrusted:
                injection_hits += len(scan_injection(text))
            redacted, n = redact_secrets(text)
            secrets_redacted += n
            tokenized, counts = self._tokenizer.tokenize(  # type: ignore[union-attr]
                redacted, policy=policy, user_id=user_id, operation_id=operation_id
            )
            detected.update(counts)
            if not untrusted:
                return tokenized
            # Los resultados de herramienta son JSON (ver ToolExecution.as_llm_output()): una vez
            # tokenizados los nombres, minimiza también los importes INDIVIDUALES que queden ligados a
            # una persona ya identificada (ajuste del punto 1 de la aprobación condicionada).
            minimized = redact_individual_amounts(tokenized, policy=policy)
            return wrap_untrusted(minimized)

        new_system = _process(request.system)
        new_messages = [
            replace(m, content=_process(m.content, untrusted=m.role == "tool")) for m in request.messages
        ]
        audit.record_inspection(
            operation_id=operation_id,
            policy=policy.value,
            provider=self._provider_name,
            model=self._model,
            detected=detected,
            tokenized=sum(detected.values()),
            injection_hits=injection_hits,
            secrets_redacted=secrets_redacted,
        )
        return replace(request, system=new_system, messages=new_messages)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        if not self._settings.enabled or self._tokenizer is None:
            async for event in self._inner.stream(request):
                yield event
            return

        user_id, operation_id = self._identity()
        policy = resolve_policy(None, default=self._settings.default_policy)
        tokenizer = self._tokenizer

        try:
            safe_request = self._sanitize_request(request, policy=policy, user_id=user_id, operation_id=operation_id)
        except Exception as exc:
            # Fallo seguro: CUALQUIER excepción al proteger la salida bloquea la llamada externa, no
            # solo UnsafeContentBlockedError — un fallo inesperado del motor no debe convertirse nunca
            # en un envío sin protección por accidente.
            audit.record_blocked(operation_id=operation_id, reason=f"{type(exc).__name__}")
            if not self._settings.fail_open:
                raise UnsafeContentBlockedError(f"Fallo al proteger la salida: {type(exc).__name__}") from exc
            safe_request = request  # pragma: no cover — solo depuración local explícita

        buffer = _StreamBuffer()
        restored_total = 0

        def _emit(text: str) -> TextDelta | None:
            nonlocal restored_total
            if not text:
                return None
            restored, n = tokenizer.restore(text, user_id=user_id, operation_id=operation_id)
            restored_total += n
            cleaned, _ = sanitize_inbound(restored)
            return TextDelta(text=cleaned) if cleaned else None

        async for event in self._inner.stream(safe_request):
            if isinstance(event, TextDelta):
                safe_chunk = buffer.feed(event.text)
                delta = _emit(safe_chunk)
                if delta is not None:
                    yield delta
                continue
            yield event

        tail = buffer.flush()
        delta = _emit(tail)
        if delta is not None:
            yield delta
        audit.record_restoration(operation_id=operation_id, restored=restored_total)
        # No se purga aquí: una operación (turno) puede implicar varias llamadas a stream() (una por
        # ronda de herramientas) y un token asignado en la ronda 1 debe poder restaurarse en la ronda 3.
        # La limpieza es por antigüedad (TTL), igual que el propio Token Vault — ver Tokenizer._sweep_stale.

    def _anonymize_for_embedding(self, text: str, *, policy: Policy) -> str:
        """A diferencia de ``tokenize()``, esto NO es reversible ni se guarda en el Token Vault: un
        vector de embedding no necesita restaurarse nunca (no es texto que vuelva a un usuario), así
        que no tiene sentido gastar una entrada del vault por cada nombre de cada CV indexado. Se
        sustituye por un marcador genérico por tipo de entidad (``<PERSON>``…), suficiente para que el
        texto vectorizado no contenga el dato personal."""
        if not text:
            return text
        entities = self._engine.analyze(text)  # type: ignore[union-attr]
        threshold = score_threshold(policy)
        relevant = [
            e for e in entities if e.score >= threshold and action_for(e.entity_type, policy) is Action.TOKENIZE
        ]
        if not relevant:
            return text
        relevant = drop_overlapping(relevant)
        relevant.sort(key=lambda e: e.start, reverse=True)
        out = text
        for entity in relevant:
            out = out[: entity.start] + f"<{entity.entity_type}>" + out[entity.end :]
        return out

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        if not self._settings.enabled or self._engine is None:
            return await self._inner.embed(texts, model)
        policy = resolve_policy(None, default=self._settings.default_policy)
        try:
            safe_texts = [self._anonymize_for_embedding(t, policy=policy) for t in texts]
        except Exception as exc:
            if self._settings.fail_open:  # pragma: no cover — solo depuración local explícita
                safe_texts = texts
            else:
                raise UnsafeContentBlockedError(
                    f"Fallo al proteger texto para embeddings: {type(exc).__name__}"
                ) from exc
        return await self._inner.embed(safe_texts, model)

    async def read_image(self, content: bytes, media_type: str, instruction: str) -> str:
        if self._settings.enabled:
            # Sección 9: el contenido multimodal no tiene hoy protección de píxeles (solo de texto). No
            # se declara cobertura completa: se bloquea explícitamente en vez de fingir que se protege.
            raise UnsafeContentBlockedError(
                "El Privacy Gateway no protege contenido de imagen todavía: lectura de imágenes "
                "bloqueada mientras esta cobertura esté pendiente (ver progreso del proyecto)."
            )
        return await self._inner.read_image(content, media_type, instruction)

    async def aclose(self) -> None:
        await self._inner.aclose()
