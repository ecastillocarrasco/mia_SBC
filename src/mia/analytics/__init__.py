"""Analytics — estadística, insights, comparación y módulo predictivo (futuro).

Módulos activos:
  stats      — StatisticsEngine: estadística descriptiva, series temporales, outliers
  insights   — InsightEngine: detección automática de hechos relevantes
  comparison — ComparisonEngine: comparación universal A vs B / N grupos

El módulo predictivo (PredictiveModel / PredictionRequest) se mantiene como
infraestructura sin implementación; requiere evaluación de alto riesgo IA (EU AI Act).
"""

# Exporta los motores analíticos activos
from mia.analytics.comparison import ComparisonResult, MetricComparison, MultiGroupComparison
from mia.analytics.insights import Insight, InsightEngine
from mia.analytics.stats import TimePoint, descriptive, detect_outliers, time_series_stats

__all__ = [
    "ComparisonResult",
    "Insight",
    "InsightEngine",
    "MetricComparison",
    "MultiGroupComparison",
    "TimePoint",
    "descriptive",
    "detect_outliers",
    "time_series_stats",
]


# ── Predictivo (infraestructura sin implementación) ──────────────────────────
# Un modelo predictivo sobre personas empleadas es de alto riesgo según el
# Reglamento Europeo de IA (Reglamento (UE) 2024/1689). No se implementa hasta
# completar la evaluación legal. La nacionalidad y cualquier proxy de origen
# étnico no se usan como variable predictiva bajo ningún concepto.

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PredictionRequest:
    person_key: str
    features: dict[str, Any]
    """Nunca debe incluir nacionalidad ni ningún proxy directo de origen étnico."""


class PredictiveModel(ABC):
    """Contrato para un modelo predictivo servido desde Azure ML.

    Sin implementación todavía: falta la evaluación de alto riesgo del Reglamento
    Europeo de IA antes de entrenar o servir nada.
    """

    @abstractmethod
    async def predict(self, request: PredictionRequest) -> dict[str, Any]:
        raise NotImplementedError
