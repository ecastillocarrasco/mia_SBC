"""Caché de ``Tokenizer.tokenize()`` por (operación, política, texto).

El system prompt es el mismo texto en todas las rondas de un turno (varios segundos de análisis NLP
sobre ~30.000 caracteres si no se cachea); repetir el análisis en cada ronda es desperdicio puro.
"""

from __future__ import annotations

from mia.privacy_gateway.policy_engine import Policy
from mia.privacy_gateway.presidio_engine import DetectedEntity
from mia.privacy_gateway.token_vault import TokenVault
from mia.privacy_gateway.tokenizer import Tokenizer

NAME = "María García López"


class CountingEngine:
    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, text: str):
        self.calls += 1
        if NAME in text:
            i = text.index(NAME)
            return [DetectedEntity("PERSON", i, i + len(NAME), 0.99, NAME)]
        return []


def _tokenizer() -> tuple[Tokenizer, CountingEngine]:
    engine = CountingEngine()
    vault = TokenVault("test-only-key-123456", 900)
    return Tokenizer(engine, vault, ttl_seconds=900.0), engine


def test_identical_text_same_operation_only_analyzed_once() -> None:
    tokenizer, engine = _tokenizer()
    text = f"Hola, soy {NAME}, repito la misma frase en cada ronda."
    first, _ = tokenizer.tokenize(text, policy=Policy.STANDARD, user_id="u1", operation_id="op-1")
    second, _ = tokenizer.tokenize(text, policy=Policy.STANDARD, user_id="u1", operation_id="op-1")
    third, _ = tokenizer.tokenize(text, policy=Policy.STANDARD, user_id="u1", operation_id="op-1")
    assert engine.calls == 1
    assert first == second == third
    assert NAME not in first


def test_different_operation_is_analyzed_again() -> None:
    """La caché nunca cruza operaciones: un turno distinto no puede reutilizar el análisis de otro."""
    tokenizer, engine = _tokenizer()
    text = f"Hola, soy {NAME}."
    tokenizer.tokenize(text, policy=Policy.STANDARD, user_id="u1", operation_id="op-1")
    tokenizer.tokenize(text, policy=Policy.STANDARD, user_id="u1", operation_id="op-2")
    assert engine.calls == 2


def test_different_policy_is_analyzed_again() -> None:
    """STRICT y STANDARD pueden tokenizar distinto (umbral/entidades distintas): no deben compartir caché."""
    tokenizer, engine = _tokenizer()
    text = f"Hola, soy {NAME}."
    tokenizer.tokenize(text, policy=Policy.STANDARD, user_id="u1", operation_id="op-1")
    tokenizer.tokenize(text, policy=Policy.STRICT, user_id="u1", operation_id="op-1")
    assert engine.calls == 2


def test_different_text_same_operation_is_analyzed_again() -> None:
    tokenizer, engine = _tokenizer()
    tokenizer.tokenize("primer mensaje", policy=Policy.STANDARD, user_id="u1", operation_id="op-1")
    tokenizer.tokenize("segundo mensaje, distinto", policy=Policy.STANDARD, user_id="u1", operation_id="op-1")
    assert engine.calls == 2


def test_purge_operation_clears_the_cache_too() -> None:
    tokenizer, engine = _tokenizer()
    text = f"Hola, soy {NAME}."
    tokenizer.tokenize(text, policy=Policy.STANDARD, user_id="u1", operation_id="op-1")
    tokenizer.purge_operation("op-1")
    tokenizer.tokenize(text, policy=Policy.STANDARD, user_id="u1", operation_id="op-1")
    assert engine.calls == 2
