"""Auditoría del Privacy Gateway: reutiliza el sistema de diagnóstico existente (mia.diagnostics) en
vez de crear uno paralelo. Nunca registra el valor original de una entidad protegida — solo tipo y
recuento. Si no hay traza activa (diagnósticos desactivados), estas llamadas no hacen nada: el gateway
funciona igual, simplemente sin esa observabilidad adicional (igual que el resto de mIA)."""

from __future__ import annotations

from collections import Counter

from mia.diagnostics import EventStage, EventStatus, current_trace


def record_inspection(
    *,
    operation_id: str,
    policy: str,
    provider: str,
    model: str,
    detected: Counter[str],
    tokenized: int,
    secrets_redacted: int,
    injection_hits: int = 0,
) -> None:
    trace = current_trace()
    if trace is None:
        return
    trace.emit(
        EventStage.PRIVACY_GATEWAY_INSPECT,
        data={
            "operation_id": operation_id,
            "policy": policy,
            "provider": provider,
            "model": model,
            "categorias_detectadas": dict(detected),
            "elementos_tokenizados": tokenized,
            "secretos_redactados": secrets_redacted,
            "posible_prompt_injection": injection_hits,
        },
    )


def record_blocked(*, operation_id: str, reason: str) -> None:
    trace = current_trace()
    if trace is None:
        return
    trace.emit(
        EventStage.PRIVACY_GATEWAY_BLOCKED,
        status=EventStatus.ERROR,
        data={"operation_id": operation_id, "motivo": reason},
    )


def record_restoration(*, operation_id: str, restored: int) -> None:
    if restored <= 0:
        return
    trace = current_trace()
    if trace is None:
        return
    trace.emit(
        EventStage.PRIVACY_GATEWAY_RESTORED,
        data={"operation_id": operation_id, "tokens_restaurados": restored},
    )
