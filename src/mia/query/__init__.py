"""Universal Query Layer — FASE A Foundation.

Módulos:
  period   — PeriodEngine: expresiones naturales → rangos de fecha explícitos
  fields   — SemanticFieldRegistry: sinónimos → campo interno
  dataset  — NormalizedDataset: contrato de datos interoperable
  engine   — UniversalQueryEngine: filter/sort/group/aggregate en memoria

Estos módulos no tocan la BD ni las tools directamente; son servicios
de apoyo que las tools usan para responder consultas más generales.
"""

from mia.query.dataset import NormalizedDataset, Row, Schema
from mia.query.engine import UniversalQueryEngine
from mia.query.fields import SemanticFieldRegistry, field_registry
from mia.query.period import PeriodEngine, ResolvedPeriod, period_engine

__all__ = [
    "NormalizedDataset",
    "PeriodEngine",
    "ResolvedPeriod",
    "Row",
    "Schema",
    "SemanticFieldRegistry",
    "UniversalQueryEngine",
    "field_registry",
    "period_engine",
]
