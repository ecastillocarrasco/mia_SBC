"""Lectura del resumen económico de una nómina (formato del proveedor de nóminas de SBC).

Misma lógica que el sistema anterior: tabla resumen «REM. TOTAL … T. A DEDUCIR»,
líquido a percibir e IRPF, con comprobación devengado − deducciones = líquido.
"""

from __future__ import annotations

import re
from typing import Any

AMOUNT = re.compile(r"-?[0-9][0-9.]*,[0-9]{2}")
SUMMARY = (
    "remuneracion_total",
    "prorrata_extras",
    "base_cotizacion_cc",
    "base_at_desempleo",
    "base_irpf",
    "total_devengado",
    "total_deducciones",
)
EXTRA_SUMMARY = ("base_irpf", "total_devengado", "total_deducciones")
HEADER = re.compile(
    r"REM\.\s*TOTAL.*?P\.P\.\s*EXTRAS.*?BASE\s*C\.C\..*?BASE\s*A\.T\.\s*Y\s*DES.*?BASE\s*I\.R\.P\.F\."
    r".*?T\.\s*DEVENGADO.*?T\.\s*A\s*DEDUCIR",
    re.IGNORECASE,
)
LIQUID = (
    re.compile(r"([0-9][0-9.]*,[0-9]{2})\s+L[ií]quido\s+a\s+[Pp]?ercibir", re.IGNORECASE),
    re.compile(r"L[ií]quido(?:\s+total)?\s+(?:a\s+[Pp]?ercibir)?.{0,40}?([0-9][0-9.]*,[0-9]{2})", re.IGNORECASE),
    re.compile(r"Neto\s+a\s+percibir.{0,40}?([0-9][0-9.]*,[0-9]{2})", re.IGNORECASE),
)


def amount_es(raw: str | None) -> float | None:
    """«1.234,56» → 1234.56"""
    if not raw:
        return None
    try:
        return float(raw.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def parse_payslip(text: str) -> dict[str, Any]:
    lines = [" ".join(x.split()) for x in text.splitlines() if x.strip()]
    is_extra = any(re.search(r"\bExtra\s*-\s*", line, re.IGNORECASE) for line in lines)
    out: dict[str, Any] = dict.fromkeys((*SUMMARY, "liquido", "irpf_importe", "irpf_porcentaje"))
    header = next((i for i, line in enumerate(lines) if HEADER.search(line)), None)
    if header is not None:
        for line in lines[header + 1 : header + 4]:
            values = AMOUNT.findall(line)
            fields = SUMMARY if len(values) == 7 else EXTRA_SUMMARY if is_extra and len(values) == 3 else None
            if fields:
                out.update({f: amount_es(v) for f, v in zip(fields, values, strict=True)})
                break
    joined = "\n".join(lines)
    for pattern in LIQUID:
        if match := pattern.search(joined):
            out["liquido"] = amount_es(match.group(1))
            break
    irpf_line = next((line for line in lines if re.search(r"Tributaci[oó]n\s+I\.?R\.?P\.?F\.?", line, re.I)), None)
    if irpf_line:
        if pct := re.search(r"\(\s*([0-9]{1,2}(?:[.,][0-9]{1,2})?)\s*%\s*\)", irpf_line):
            out["irpf_porcentaje"] = amount_es(pct.group(1).replace(".", ","))
        if amt := re.search(r"\)\s*([0-9][0-9.]*,[0-9]{2})(?:\s|$)", irpf_line):
            out["irpf_importe"] = amount_es(amt.group(1))
    if out["irpf_porcentaje"] is None and (
        pct := re.search(r"(?:I\.?R\.?P\.?F\.?|retenci[oó]n).{0,30}?([0-9]{1,2}(?:[.,][0-9]{1,2})?)\s*%", joined, re.I)
    ):
        out["irpf_porcentaje"] = amount_es(pct.group(1).replace(".", ","))
    check = None
    if None not in (out["total_devengado"], out["total_deducciones"], out["liquido"]):
        diff = round(out["total_devengado"] - out["total_deducciones"] - out["liquido"], 2)
        check = {"cuadra": abs(diff) <= 0.02, "diferencia": diff}
    return {
        "tipo": "paga_extra" if is_extra else "nomina",
        "importes": {k: v for k, v in out.items() if v is not None},
        "comprobacion": check,
        "lectura_completa": out["liquido"] is not None,
    }
