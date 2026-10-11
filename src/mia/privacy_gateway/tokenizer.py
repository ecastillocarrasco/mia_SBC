"""Sustituye entidades detectadas por pseudo-tokens reversibles: ``[PERSON_001]``, ``[ES_DNI_NIE_001]``…

Mismo valor -> mismo token dentro de una misma operación (coherencia: si "María García" aparece en el
system prompt y en un resultado de herramienta, el LLM ve el mismo [PERSON_001] en ambos, no dos
distintos) — pero el token nunca lleva el valor original codificado, solo un número de secuencia.
"""

from __future__ import annotations

import re
import threading
import time
from collections import Counter

from mia.privacy_gateway.policy_engine import Action, Policy, action_for, score_threshold
from mia.privacy_gateway.presidio_engine import PresidioEngine, drop_overlapping
from mia.privacy_gateway.token_vault import TokenVault

_TOKEN_RE = re.compile(r"\[([A-Z_]+?)_(\d{3,})\]")


class Tokenizer:
    """``_assigned``/``_counters`` viven mientras dura la operación (todas las rondas de un mismo turno,
    no solo una llamada a ``stream()``): hay que poder restaurar en la ronda 3 un token asignado en la
    ronda 1. No se purgan al final de cada ``stream()`` (eso rompería esa coherencia entre rondas);
    se barren por antigüedad (TTL) de forma oportunista, igual que ya hace el propio Token Vault."""

    def __init__(self, engine: PresidioEngine, vault: TokenVault, *, ttl_seconds: float = 900.0) -> None:
        self._engine = engine
        self._vault = vault
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        # (operation_id, entity_type, value) -> token
        self._assigned: dict[tuple[str, str, str], str] = {}
        self._counters: dict[tuple[str, str], int] = {}
        self._last_seen: dict[str, float] = {}

    def _token_for_value(self, entity_type: str, value: str, *, user_id: str, operation_id: str) -> str:
        key = (operation_id, entity_type, value)
        with self._lock:
            self._last_seen[operation_id] = time.monotonic()
            token = self._assigned.get(key)
            if token is None:
                counter_key = (operation_id, entity_type)
                self._counters[counter_key] = self._counters.get(counter_key, 0) + 1
                token = f"[{entity_type}_{self._counters[counter_key]:03d}]"
                self._assigned[key] = token
        self._vault.store(token.strip("[]"), value, user_id=user_id, operation_id=operation_id)
        return token

    def _sweep_stale(self) -> None:
        cutoff = time.monotonic() - self._ttl
        with self._lock:
            stale_ops = [op for op, seen in self._last_seen.items() if seen < cutoff]
            if not stale_ops:
                return
            stale_set = set(stale_ops)
            self._assigned = {k: v for k, v in self._assigned.items() if k[0] not in stale_set}
            self._counters = {k: v for k, v in self._counters.items() if k[0] not in stale_set}
            for op in stale_ops:
                del self._last_seen[op]

    def tokenize(
        self, text: str, *, policy: Policy, user_id: str, operation_id: str
    ) -> tuple[str, Counter[str]]:
        """Devuelve (texto_con_pseudo_tokens, recuento de entidades por tipo)."""
        self._sweep_stale()
        if not text:
            return text, Counter()
        entities = self._engine.analyze(text)
        threshold = score_threshold(policy)
        relevant = [
            e for e in entities if e.score >= threshold and action_for(e.entity_type, policy) is Action.TOKENIZE
        ]
        if not relevant:
            return text, Counter()
        relevant = drop_overlapping(relevant)
        # de derecha a izquierda para no desplazar los índices de las entidades ya procesadas
        relevant.sort(key=lambda e: e.start, reverse=True)
        out = text
        counts: Counter[str] = Counter()
        for entity in relevant:
            token = self._token_for_value(entity.entity_type, entity.text, user_id=user_id, operation_id=operation_id)
            out = out[: entity.start] + token + out[entity.end :]
            counts[entity.entity_type] += 1
        return out, counts

    def restore(self, text: str, *, user_id: str, operation_id: str) -> tuple[str, int]:
        """Sustituye cada [TIPO_NNN] por su valor real SOLO si el token pertenece a esta operación y
        usuario; un token desconocido, ajeno o alterado se deja tal cual (nunca se adivina ni se oculta
        el hueco: es preferible mostrar el token literal a restaurar algo incorrecto). Devuelve también
        cuántos se restauraron de verdad."""
        restored_count = 0

        def _replace(match: re.Match[str]) -> str:
            nonlocal restored_count
            token_body = f"{match.group(1)}_{match.group(2)}"
            resolved = self._vault.resolve(token_body, user_id=user_id, operation_id=operation_id)
            if resolved is not None:
                restored_count += 1
                return resolved
            return match.group(0)

        return _TOKEN_RE.sub(_replace, text), restored_count

    def purge_operation(self, operation_id: str) -> None:
        with self._lock:
            stale = [k for k in self._assigned if k[0] == operation_id]
            for k in stale:
                del self._assigned[k]
            stale_counters = [k for k in self._counters if k[0] == operation_id]
            for k in stale_counters:
                del self._counters[k]
        self._vault.purge_operation(operation_id)
