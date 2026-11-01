"""Keep individual financial values local under every privacy policy.

Identity fields define individual scope, inherited by nested payslip/concept records.
This is independent of whether statistical NER recognized the name. Backend calculations,
local presentations and files retain their original values. Aggregate values are preserved.
"""

from __future__ import annotations

import json
from typing import Any

from mia.privacy_gateway.policy_engine import Policy

_INDIVIDUAL_AMOUNT_KEYS = frozenset(
    {
        "importe",
        "liquido",
        "total_devengado",
        "coste_total_empresa",
        "coste_empresa_ss",
        "salario",
        "sueldo",
        "importes",
        "remuneracion_total",
        "prorrata_extras",
        "base_cotizacion_cc",
        "base_at_desempleo",
        "base_irpf",
        "total_deducciones",
        "irpf_porcentaje",
        "irpf_importe",
        "coste_empresa",
        "aportacion_empresa",
        "total_aportacion_empresa",
        "devengos",
        "deducciones",
        "diferencia",
        "base",
        "tipo_pct",
    }
)
_PERSON_KEYS = frozenset({"persona", "nombre", "empleado", "name", "employee_id", "empleado_id", "person_key"})
_REDACTED_AMOUNT = "<IMPORTE_INDIVIDUAL_PROTEGIDO>"
_TEMPORAL_OR_POSITION_KEYS = frozenset({"anio", "year", "mes", "month", "puesto_en_el_ranking"})


def _has_identified_person(obj: dict[str, Any]) -> bool:
    # Field semantics are authoritative even when NER misses an unusual name.
    return any(obj.get(key) not in (None, "", [], {}) for key in _PERSON_KEYS)


def _walk(obj: Any, *, individual: bool = False) -> Any:
    if isinstance(obj, dict):
        identified = individual or _has_identified_person(obj)
        for key, value in obj.items():
            sensitive_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if (
                identified
                and key not in _TEMPORAL_OR_POSITION_KEYS
                and (key in _INDIVIDUAL_AMOUNT_KEYS or sensitive_number)
                and value is not None
            ):
                obj[key] = _REDACTED_AMOUNT
            else:
                obj[key] = _walk(value, individual=identified)
        return obj
    if isinstance(obj, list):
        return [_walk(item, individual=individual) for item in obj]
    return obj


def redact_individual_amounts(tool_result_json: str, *, policy: Policy) -> str:
    """Minimize known structured individual values. All policies share this baseline.

    Unstructured prose requires the other gateway safeguards; it is not certified by this function.
    """
    try:
        parsed = json.loads(tool_result_json)
    except (ValueError, TypeError):
        return tool_result_json
    return json.dumps(_walk(parsed), ensure_ascii=False, default=str)
