"""Resolución de nivel de modelo configurable (Bloque II, Fase F): FAST/BALANCED/ADVANCED.

No introduce un segundo proveedor ni un segundo camino hacia el LLM: el nivel solo decide QUÉ nombre
de modelo lleva una ``LLMRequest`` concreta (campo ``model``, ver ``mia.llm.base``); la petición sigue
pasando por el mismo ``LLMProvider`` ya envuelto por el Privacy Gateway que usa el resto de mIA."""

from __future__ import annotations

from mia.settings import LLMSettings, ModelTier


def model_for_tier(settings: LLMSettings, tier: ModelTier) -> str:
    return {
        ModelTier.FAST: settings.model_fast,
        ModelTier.BALANCED: settings.model,
        ModelTier.ADVANCED: settings.model_advanced,
    }[tier]
