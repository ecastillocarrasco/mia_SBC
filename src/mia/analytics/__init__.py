"""Predictivo de RRHH (Azure ML) — vacío por ahora.

Aviso explícito: un modelo predictivo sobre personas empleadas es de **alto riesgo** según el
Reglamento Europeo de IA (Reglamento (UE) 2024/1689, sistemas de IA en el ámbito laboral). No
se implementa en esta sesión -falta la evaluación legal-; esto es solo el hueco arquitectónico
para cuando exista, estructuralmente separado de ``conversation/`` (el LLM) y de
``modules/rrhh`` (los dominios transaccionales): un predictivo no debe acoplarse a ninguno
de los dos para poder auditarlo, explicarlo y, si hiciera falta, desactivarlo por separado.

Regla innegociable para cuando se implemente: la nacionalidad (``Employee.nationality``) y
cualquier variable que actúe como proxy de origen étnico NO se usan como variable predictiva
bajo ningún concepto.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PredictionRequest:
    person_key: str
    features: dict[str, Any]
    """Nunca debe incluir nacionalidad ni ningún proxy directo de origen étnico (ver aviso del
    módulo). Validar esto aquí, no confiar en que quien construya el request lo recuerde."""


class PredictiveModel(ABC):
    """Contrato para un modelo predictivo servido desde Azure ML.

    Sin implementación todavía: falta la evaluación de alto riesgo del Reglamento Europeo de
    IA (documentación técnica, supervisión humana, registro de decisiones) antes de entrenar
    o servir nada.
    """

    @abstractmethod
    async def predict(self, request: PredictionRequest) -> dict[str, Any]:
        raise NotImplementedError
