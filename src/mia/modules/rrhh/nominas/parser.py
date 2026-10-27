"""Lectura del resumen económico de una nómina (formato del proveedor de nóminas de SBC).

Misma lógica que el sistema anterior: tabla resumen «REM. TOTAL … T. A DEDUCIR»,
líquido a percibir e IRPF, con comprobación devengado − deducciones = líquido.
Además extrae el desglose de conceptos salariales y la aportación de la empresa a la SS.
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

# ── conceptos salariales ──────────────────────────────────────────────────────
_CONCEPTS_HEADER = re.compile(
    r"CUANTIA\s+PRECIO.*?CONCEPTO.*?DEVENGOS",
    re.IGNORECASE | re.DOTALL,
)
_CONCEPTS_END = re.compile(r"\bREM\.\s*TOTAL\b", re.IGNORECASE)
# Devengos: líneas marcadas con * (el asterisco es del formato del proveedor)
_DEVENGO = re.compile(r"\*([^\n\r*]+?)\s+(-?[0-9][0-9.]*,[0-9]{2})")
# Deducciones: líneas que empiezan por Cotización, Descuento, Retención o Tribulación IRPF
_DEDUCCION = re.compile(
    r"((?:Cotizaci[oó]n|Descuento|Retenci[oó]n|Tribulaci[oó]n\s+I\.?R\.?P\.?F?\.?)"
    r"[^\n\r]+)\s+(-?[0-9][0-9.]*,[0-9]{2})\s*(?:\n|\r|$)",
    re.MULTILINE | re.IGNORECASE,
)

# ── aportación empresa a la SS ────────────────────────────────────────────────
_SS_START = re.compile(r"APORTACI[OÓ]N\s+EMPRESA", re.IGNORECASE)
# Líneas con CONCEPTO  BASE  TIPO%  APORTACION — concepto greedy sin dígitos para capturar nombre completo
_SS_LINE = re.compile(
    r"([A-Za-záéíóúÁÉÍÓÚñÑüÜ][^0-9\n\r%]{3,60})\s+"
    r"(-?[0-9][0-9.]*,[0-9]{2})\s+"
    r"([0-9]{1,3}[,.]?[0-9]*)\s*%\s+"
    r"(-?[0-9][0-9.]*,[0-9]{2})\s*(?:\n|\r|$)",
    re.MULTILINE | re.IGNORECASE,
)


def amount_es(raw: str | None) -> float | None:
    """«1.234,56» → 1234.56"""
    if not raw:
        return None
    try:
        return float(raw.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def parse_concepts(text: str) -> dict[str, Any]:
    """Extrae el desglose de conceptos salariales (devengos y deducciones por línea)."""
    header = _CONCEPTS_HEADER.search(text)
    end = _CONCEPTS_END.search(text)
    if not header or not end or header.end() >= end.start():
        return {}
    section = text[header.end() : end.start()]
    devengos = [
        {"concepto": m.group(1).strip(), "importe": amount_es(m.group(2))}
        for m in _DEVENGO.finditer(section)
        if m.group(1).strip()
    ]
    deducciones = [
        {"concepto": m.group(1).strip(), "importe": amount_es(m.group(2))}
        for m in _DEDUCCION.finditer(section)
        if m.group(1).strip()
    ]
    if not devengos and not deducciones:
        return {}
    return {"devengos": devengos, "deducciones": deducciones}


def parse_employer_ss(text: str) -> dict[str, Any]:
    """Extrae la aportación de la empresa a la SS (bases, tipos y totales)."""
    ss_start = _SS_START.search(text)
    if not ss_start:
        return {}
    section = text[ss_start.end() :]
    lines = []
    for m in _SS_LINE.finditer(section):
        try:
            tipo = float(m.group(3).replace(",", "."))
        except ValueError:
            tipo = None
        lines.append(
            {
                "concepto": m.group(1).strip(),
                "base": amount_es(m.group(2)),
                "tipo_pct": tipo,
                "aportacion_empresa": amount_es(m.group(4)),
            }
        )
    if not lines:
        return {}
    total = round(sum(ln["aportacion_empresa"] for ln in lines if ln["aportacion_empresa"]), 2)
    return {"desglose": lines, "total_aportacion_empresa": total}


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
    result: dict[str, Any] = {
        "tipo": "paga_extra" if is_extra else "nomina",
        "importes": {k: v for k, v in out.items() if v is not None},
        "comprobacion": check,
        "lectura_completa": out["liquido"] is not None,
    }
    if concepts := parse_concepts(joined):
        result["conceptos"] = concepts
    if ss := parse_employer_ss(joined):
        result["coste_empresa"] = ss
    return result
