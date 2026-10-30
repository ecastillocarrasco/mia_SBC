"""Valores y formatos numéricos compartidos por Excel y su verificador."""

import math
import re
from typing import Any


def typed_value(value: Any) -> tuple[Any, str | None]:
    if not isinstance(value, str):
        return value, None
    raw = value.strip()
    eur = re.fullmatch(r"(-?)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s*€", raw)
    if eur:
        integer = eur.group(2).replace(".", "")
        decimals = (eur.group(3) or "0").ljust(2, "0")
        return float(f"{eur.group(1)}{integer}.{decimals}"), '#,##0.00 "€"'
    pct = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)%", raw)
    if pct:
        return float(pct.group(1).replace(",", ".")) / 100, "0.0%"
    return value, None


def pptx_row_fragments(row: list[Any], columns: int) -> list[list[str]]:
    """Fragmenta celdas sin perder caracteres ni desplazar sus columnas."""
    per_cell = max(30, min(100, 290 // columns))
    values = ["" if c >= len(row) or row[c] is None else str(row[c]) for c in range(columns)]
    count = max(1, *(math.ceil(len(value) / per_cell) for value in values))
    return [[value[i * per_cell : (i + 1) * per_cell] for value in values] for i in range(count)]
