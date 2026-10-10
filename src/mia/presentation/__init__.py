"""Módulo de intención y profundidad de presentación de mIA."""

from mia.presentation.intent import (
    PresentationIntent,
    QueryAnalysis,
    ResponseDepth,
    build_presentation_hint,
    classify_query,
)

__all__ = [
    "PresentationIntent",
    "QueryAnalysis",
    "ResponseDepth",
    "build_presentation_hint",
    "classify_query",
]
