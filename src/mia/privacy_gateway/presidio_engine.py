"""Envoltorio de Microsoft Presidio: analizador (detección) + anonimizador (sustitución).

Carga perezosa: el modelo spaCy en español (~500 MB) solo se carga la primera vez que se analiza
texto de verdad, nunca al importar el módulo — así arrancar la app o correr los tests que no activan
el gateway no paga ese coste.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from mia.privacy_gateway.custom_recognizers import build_spanish_recognizers
from mia.privacy_gateway.exceptions import UnsafeContentBlockedError
from mia.text import normalize_key

_LANGUAGE = "es"

_ASSISTANT_NAME = "mia"
_ADDRESS_FILLER_WORDS = frozenset(
    {
        "mia",
        "hola",
        "holaa",
        "holaaa",
        "ey",
        "hey",
        "buenas",
        "buenos",
        "dias",
        "tardes",
        "noches",
        "saludos",
        "que",
        "tal",
        "estas",
        "vas",
        "como",
        "andas",
    }
)
"""Muletillas de saludo/dirección + el propio nombre del asistente. El modelo spaCy en español, al
analizar frases cortas como "hola mia", fusiona el saludo y el nombre en UN SOLO tramo PERSON (lo
mismo le pasa con "hola juan" o "hola maria" — no es un sesgo específico de "mia", es cómo trata
cualquier "saludo + nombre en minúsculas" corto). Un ``allow_list`` de Presidio (coincidencia EXACTA
contra el tramo completo) nunca dispara aquí porque el tramo es "hola mia", no "mia" suelto."""


def _is_assistant_address_only(text: str) -> bool:
    """True solo si TODAS las palabras del tramo detectado son muletillas de saludo o el propio
    nombre del asistente, y aparece "mia" entre ellas — nunca si el tramo contiene cualquier otra
    palabra, que podría ser parte del nombre real de un tercero (p. ej. "Juan Mia López" se queda
    protegido: "juan" y "lópez" no están en la lista, así que no se descarta la entidad)."""
    words = normalize_key(text).split()
    return bool(words) and _ASSISTANT_NAME in words and all(w in _ADDRESS_FILLER_WORDS for w in words)


@dataclass(frozen=True, slots=True)
class DetectedEntity:
    entity_type: str
    start: int
    end: int
    score: float
    text: str


def drop_overlapping(entities: list[DetectedEntity]) -> list[DetectedEntity]:
    """Presidio puede devolver dos entidades de TIPOS distintos (p. ej. su ``ES_NIF`` nativo y nuestro
    ``ES_DNI_NIE`` propio, con verificación de dígito de control) sobre el MISMO tramo de texto.
    Sustituir ambas por separado corrompería la cadena (los índices de la segunda ya no serían
    válidos tras aplicar la primera). Se queda una sola entidad por tramo que se solape — la de mayor
    puntuación — antes de que cualquier llamador haga sustituciones basadas en (start, end)."""
    by_score = sorted(entities, key=lambda e: e.score, reverse=True)
    kept: list[DetectedEntity] = []
    for entity in by_score:
        if any(entity.start < k.end and k.start < entity.end for k in kept):
            continue
        kept.append(entity)
    return kept


class PresidioEngine:
    """Un único motor por proceso (el modelo NLP es caro de cargar); seguro para llamadas concurrentes
    porque `analyze`/`anonymize` de Presidio no mutan estado compartido entre llamadas."""

    def __init__(self, spacy_model: str) -> None:
        self._spacy_model = spacy_model
        self._analyzer: Any = None
        self._anonymizer: Any = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._analyzer is not None:
            return
        with self._lock:
            if self._analyzer is not None:  # otro hilo lo cargó mientras esperábamos
                return
            try:
                from presidio_analyzer import AnalyzerEngine  # noqa: PLC0415 — carga perezosa deliberada
                from presidio_analyzer.nlp_engine import NlpEngineProvider  # noqa: PLC0415
                from presidio_anonymizer import AnonymizerEngine  # noqa: PLC0415

                provider = NlpEngineProvider(
                    nlp_configuration={
                        "nlp_engine_name": "spacy",
                        "models": [{"lang_code": _LANGUAGE, "model_name": self._spacy_model}],
                        # MISC no está en PERSONAL_ENTITIES (policy_engine.py): nunca se tokeniza, así que
                        # descartarlo aquí no cambia qué se protege, solo evita el aviso repetido de Presidio
                        # ("Entity MISC is not mapped...") en cada documento indexado.
                        "ner_model_configuration": {"labels_to_ignore": ["MISC"]},
                    }
                )
                nlp_engine = provider.create_engine()
                analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=[_LANGUAGE])
                for recognizer in build_spanish_recognizers():
                    analyzer.registry.add_recognizer(recognizer)
                self._analyzer = analyzer
                self._anonymizer = AnonymizerEngine()
            except Exception as exc:  # pragma: no cover — depende del entorno (modelo no instalado, etc.)
                raise UnsafeContentBlockedError(
                    f"No se pudo inicializar el motor Presidio: {type(exc).__name__}"
                ) from exc

    def analyze(self, text: str, *, entities: list[str] | None = None) -> list[DetectedEntity]:
        """Detecta entidades sensibles en ``text``. Lanza UnsafeContentBlockedError si Presidio no
        pudo cargarse — nunca devuelve una lista vacía fingiendo que no hay nada que proteger."""
        if not text:
            return []
        self._ensure_loaded()
        try:
            results = self._analyzer.analyze(text=text, language=_LANGUAGE, entities=entities)
        except Exception as exc:  # pragma: no cover
            raise UnsafeContentBlockedError(f"Fallo del analizador Presidio: {type(exc).__name__}") from exc
        detected = [DetectedEntity(r.entity_type, r.start, r.end, r.score, text[r.start : r.end]) for r in results]
        return [e for e in detected if not (e.entity_type == "PERSON" and _is_assistant_address_only(e.text))]


_engine: PresidioEngine | None = None
_engine_lock = threading.Lock()


def get_presidio_engine(spacy_model: str) -> PresidioEngine:
    global _engine  # noqa: PLW0603 — doble comprobación con cerrojo, patrón singleton estándar
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = PresidioEngine(spacy_model)
    return _engine
