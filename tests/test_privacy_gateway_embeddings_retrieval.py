"""Ajuste 2 de la aprobación condicionada del Bloque I: prueba comparativa de calidad de recuperación
semántica antes y después de anonimizar texto para embeddings (ver ``PrivacyGateway._anonymize_for_embedding``
en ``mia/privacy_gateway/gateway.py``).

Se usa el embedding determinista de bolsa de palabras de ``FakeLLMProvider.embed`` (ver ``mia/llm/fake.py``):
es el único mecanismo de embedding real y reproducible disponible en este entorno (no se simula una
API externa de verdad; no se inventan métricas). Corpus y consultas son sintéticos, con una respuesta
esperada conocida de antemano (ground truth), tal y como pide el ajuste.

Resultado documentado (ver también PRIVACY_GATEWAY_PROGRESS.md):
  * Recuperación por TEMA/CONTENIDO (lo único que el motor de informes/conocimiento necesita en la
    práctica): sin degradación. El vocabulario que decide la coincidencia no es el dato personal que
    se tokeniza.
  * Recuperación buscando el NOMBRE LITERAL de una persona: se degrada, A PROPÓSITO — es justo lo que
    protege la anonimización. No es un defecto a mitigar en el embedding: la localización de una
    persona concreta ya se resuelve en mIA con búsqueda estructurada por clave (``name_key``/
    ``person_key``, p. ej. en ``buscar_empleado``), no con recuperación semántica por vector. Por eso
    no se propone ninguna "estrategia alternativa" distinta de la que ya existe en el dominio.
"""

from __future__ import annotations

from mia.llm.fake import FakeLLMProvider
from mia.privacy_gateway.context_manager import set_operation_context
from mia.privacy_gateway.gateway import PrivacyGateway
from mia.settings import PrivacyGatewaySettings

_CORPUS = [
    ("cocina", "El cocinero Marta Ruiz, DNI 12345678Z, prepara mariscos y paellas en la cocina del restaurante cada mediodía."),
    ("mantenimiento", "El técnico Carlos López, DNI 23456789D, revisa la caldera y los aires acondicionados del hotel cada semana."),
    ("recepcion", "La recepcionista Sofía Pérez, DNI 34567890V, gestiona el check-in de huéspedes y las reservas de habitaciones."),
    ("animacion", "El animador Diego Vidal, DNI 45678901G, organiza actividades infantiles y juegos en la piscina para los turistas."),
]

_TOPIC_QUERIES = [
    ("¿quién prepara mariscos y paellas en la cocina del restaurante?", "cocina"),
    ("¿quién revisa la caldera y los aires acondicionados del hotel?", "mantenimiento"),
    ("¿quién gestiona el check-in de huéspedes y las reservas de habitaciones?", "recepcion"),
    ("¿quién organiza actividades infantiles y juegos en la piscina?", "animacion"),
]

_NAME_QUERIES = [
    ("¿qué hace Marta Ruiz?", "cocina"),
    ("¿qué hace Carlos López?", "mantenimiento"),
    ("¿qué hace Sofía Pérez?", "recepcion"),
    ("¿qué hace Diego Vidal?", "animacion"),
]


def _settings(**overrides: object) -> PrivacyGatewaySettings:
    base = {"enabled": True, "vault_key": "clave-de-prueba-no-real", "vault_ttl_seconds": 60}
    base.update(overrides)
    return PrivacyGatewaySettings(**base)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _precision_at_1(
    doc_vectors: list[list[float]],
    doc_labels: list[str],
    queries: list[tuple[str, str]],
    query_vectors: list[list[float]],
) -> float:
    hits = 0
    for (_, expected_label), q_vec in zip(queries, query_vectors, strict=True):
        sims = [_cosine(q_vec, d) for d in doc_vectors]
        best_label = doc_labels[sims.index(max(sims))]
        if best_label == expected_label:
            hits += 1
    return hits / len(queries)


async def test_topic_retrieval_precision_is_preserved_after_anonymization() -> None:
    """Las consultas por tema/contenido deben recuperar el documento correcto igual de bien antes y
    después de anonimizar: cero degradación aceptable, no "aceptable pero menor"."""
    labels = [label for label, _ in _CORPUS]
    raw_texts = [text for _, text in _CORPUS]

    fake = FakeLLMProvider()
    raw_doc_vectors = await fake.embed(raw_texts, model="test-embed")

    gateway = PrivacyGateway(fake, _settings(), provider_name="test", model="test-model")
    set_operation_context(user_id="u-retrieval", operation_id="op-retrieval-topic")
    anon_doc_vectors = await gateway.embed(raw_texts, model="test-embed")

    # Las consultas del usuario no llevan datos personales: se embeben igual en ambos escenarios.
    topic_query_vectors = await fake.embed([q for q, _ in _TOPIC_QUERIES], model="test-embed")

    precision_before = _precision_at_1(raw_doc_vectors, labels, _TOPIC_QUERIES, topic_query_vectors)
    precision_after = _precision_at_1(anon_doc_vectors, labels, _TOPIC_QUERIES, topic_query_vectors)

    assert precision_before == 1.0
    assert precision_after == 1.0


async def test_name_based_retrieval_degrades_after_anonymization_by_design() -> None:
    """Límite documentado, no un fallo descubierto por sorpresa: buscar por el nombre literal de una
    persona deja de funcionar una vez anonimizado el corpus, porque el nombre ya no existe en el texto
    indexado. Es exactamente la protección que se pidió, no un efecto secundario."""
    labels = [label for label, _ in _CORPUS]
    raw_texts = [text for _, text in _CORPUS]

    fake = FakeLLMProvider()
    raw_doc_vectors = await fake.embed(raw_texts, model="test-embed")

    gateway = PrivacyGateway(fake, _settings(), provider_name="test", model="test-model")
    set_operation_context(user_id="u-retrieval", operation_id="op-retrieval-name")
    anon_doc_vectors = await gateway.embed(raw_texts, model="test-embed")

    name_query_vectors = await fake.embed([q for q, _ in _NAME_QUERIES], model="test-embed")

    precision_before = _precision_at_1(raw_doc_vectors, labels, _NAME_QUERIES, name_query_vectors)
    precision_after = _precision_at_1(anon_doc_vectors, labels, _NAME_QUERIES, name_query_vectors)

    assert precision_before == 1.0  # antes de anonimizar, el nombre coincide literalmente
    assert precision_after < precision_before  # degradación esperada y documentada, no accidental
