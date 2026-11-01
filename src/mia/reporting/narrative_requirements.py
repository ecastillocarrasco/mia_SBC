"""Explicit narrative sections requested by the user, separate from data-domain routing."""

from __future__ import annotations

import re
from typing import Any

from mia.text import normalize_key

_KINDS = {"hecho": "fact", "hipotesis": "hypothesis", "recomendacion": "recommendation", "conclusion": "interpretation"}
_TERMS = r"hechos?|hipotesis|recomendacion(?:es)?|conclusion(?:es)?"


def usable_statement(statement: dict[str, Any]) -> bool:
    evidence = statement.get("evidence") or {}
    return not any(evidence.get(flag) for flag in ("blocked", "period_blocked", "privacy_blocked"))


def requested_narrative_kinds(request: str) -> frozenset[str]:
    text = normalize_key(request)
    excluded = " ".join(
        re.findall(
            rf"\b(?:sin|omite|omitir|excluye|no incluyas|no incluir)\s+((?:(?:{_TERMS})|las?|los|y|ni|,|\s)+)", text
        )
    )
    return frozenset(
        kind
        for term, kind in _KINDS.items()
        if re.search(rf"\b{term}(?:es|s)?\b", text) and not re.search(rf"\b{term}(?:es|s)?\b", excluded)
    )
