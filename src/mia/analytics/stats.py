"""StatisticsEngine — estadística descriptiva, series temporales y detección de tendencias.

Diseño:
  * Los cálculos son DETERMINISTAS: nunca pide al LLM que calcule medias o percentiles.
  * Trabaja sobre listas de floats o sobre NormalizedDataset.
  * Resultados siempre son dicts serializables (JSON-safe).
  * No hay acceso a BD aquí: recibe datos ya procesados.

Categorías:
  descriptive  — count, sum, mean, median, mode, min, max, range,
                  percentiles, variance, stddev, cv, frequency
  temporal     — evolución, MoM, YoY, YTD, rolling avg, cumsum, estacionalidad
  outlier      — z-score, IQR, cambios bruscos
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from statistics import mean, median, stdev, variance
from typing import Any


# ────────────────────────────────────────────────────────────────── descriptiva
def descriptive(values: list[float], *, label: str = "valor") -> dict[str, Any]:
    """Estadística descriptiva completa de una lista numérica."""
    clean = [v for v in values if v is not None and not math.isnan(v)]
    n = len(clean)
    if n == 0:
        return {"count": 0, "nota": "Sin valores numéricos"}

    sorted_v = sorted(clean)
    out: dict[str, Any] = {
        "campo": label,
        "count": n,
        "sum": round(sum(clean), 4),
        "mean": round(mean(clean), 4),
        "median": round(median(clean), 4),
        "min": round(min(clean), 4),
        "max": round(max(clean), 4),
        "range": round(max(clean) - min(clean), 4),
    }
    if n >= 2:
        out["stddev"] = round(stdev(clean), 4)
        out["variance"] = round(variance(clean), 4)
        cv = (stdev(clean) / mean(clean) * 100) if mean(clean) != 0 else None
        out["cv_pct"] = round(cv, 2) if cv is not None else None

    # percentiles via interpolación lineal
    if n >= 4:
        def pct(p: float) -> float:
            idx = (n - 1) * p
            lo, hi = int(idx), min(int(idx) + 1, n - 1)
            return round(sorted_v[lo] + (idx - lo) * (sorted_v[hi] - sorted_v[lo]), 4)

        out["p10"] = pct(0.10)
        out["p25"] = pct(0.25)
        out["p75"] = pct(0.75)
        out["p90"] = pct(0.90)

    # moda (solo si hay duplicados)
    cnt = Counter(round(v, 2) for v in clean)
    most_common_val, most_common_freq = cnt.most_common(1)[0]
    if most_common_freq > 1:
        out["mode"] = most_common_val
        out["mode_freq"] = most_common_freq

    return out


# ────────────────────────────────────────────────────────────────── frecuencia
def frequency_distribution(
    values: list[Any], *, max_buckets: int = 20
) -> dict[str, Any]:
    """Distribución de frecuencias para valores categóricos o numéricos discretos."""
    cnt = Counter(str(v) if not isinstance(v, (int, float, bool)) else v for v in values if v is not None)
    total = sum(cnt.values())
    if total == 0:
        return {"total": 0, "distribution": []}
    top = cnt.most_common(max_buckets)
    return {
        "total": total,
        "unique": len(cnt),
        "distribution": [
            {"value": k, "count": v, "pct": round(v / total * 100, 2)}
            for k, v in top
        ],
    }


# ────────────────────────────────────────────────────────────────── series temporales
@dataclass(frozen=True, slots=True)
class TimePoint:
    label: str
    """Etiqueta del periodo (p. ej. '2026-01', 'enero', 'Q1 2026')."""
    value: float | None


def time_series_stats(points: list[TimePoint]) -> dict[str, Any]:
    """Analiza una serie temporal: evolución, MoM, tendencia, estacionalidad básica."""
    valid = [(p.label, p.value) for p in points if p.value is not None]
    n = len(valid)
    if n == 0:
        return {"count": 0, "nota": "Sin puntos temporales"}

    labels = [p[0] for p in valid]
    values = [p[1] for p in valid]

    out: dict[str, Any] = {
        "count": n,
        "labels": labels,
        "values": values,
        "min": {"label": labels[values.index(min(values))], "value": round(min(values), 4)},
        "max": {"label": labels[values.index(max(values))], "value": round(max(values), 4)},
        "first": {"label": labels[0], "value": round(values[0], 4)},
        "last": {"label": labels[-1], "value": round(values[-1], 4)},
    }

    # Variación absoluta y porcentual primero→último
    if n >= 2:
        abs_change = values[-1] - values[0]
        pct_change = (abs_change / abs(values[0]) * 100) if values[0] != 0 else None
        out["total_change"] = {
            "absolute": round(abs_change, 4),
            "pct": round(pct_change, 2) if pct_change is not None else None,
            "direction": "up" if abs_change > 0 else ("down" if abs_change < 0 else "flat"),
        }

    # MoM (mes a mes) — variación entre periodos consecutivos
    if n >= 2:
        mom = []
        for i in range(1, n):
            prev, curr = values[i - 1], values[i]
            abs_d = curr - prev
            pct_d = (abs_d / abs(prev) * 100) if prev != 0 else None
            mom.append({
                "from": labels[i - 1],
                "to": labels[i],
                "absolute": round(abs_d, 4),
                "pct": round(pct_d, 2) if pct_d is not None else None,
            })
        out["period_changes"] = mom
        # Mayor incremento / mayor caída
        mom_pct = [(m, m["pct"]) for m in mom if m["pct"] is not None]
        if mom_pct:
            best = max(mom_pct, key=lambda x: x[1])
            worst = min(mom_pct, key=lambda x: x[1])
            out["biggest_increase"] = best[0]
            out["biggest_drop"] = worst[0]

    # Tendencia lineal simple (regresión)
    if n >= 3:
        x = list(range(n))
        x_mean = mean(x)
        y_mean = mean(values)
        num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, values, strict=True))
        den = sum((xi - x_mean) ** 2 for xi in x)
        slope = num / den if den != 0 else 0
        trend = "increasing" if slope > 0.01 else ("decreasing" if slope < -0.01 else "flat")
        out["trend"] = {"direction": trend, "slope_per_period": round(slope, 6)}

    # Rolling average (ventana 3)
    if n >= 3:
        rolling = []
        window = 3
        for i in range(n):
            if i < window - 1:
                rolling.append(None)
            else:
                rolling.append(round(mean(values[i - window + 1: i + 1]), 4))
        out["rolling_avg_3"] = rolling

    # Acumulado
    cumsum = []
    acc = 0.0
    for v in values:
        acc += v
        cumsum.append(round(acc, 4))
    out["cumulative"] = cumsum

    return out


# ────────────────────────────────────────────────────────────────── outliers
def detect_outliers(
    values: list[float],
    *,
    method: str = "iqr",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Detecta valores atípicos usando IQR o z-score."""
    clean = [v for v in values if v is not None and not math.isnan(v)]
    n = len(clean)
    if n < 4:
        return {"method": method, "outliers": [], "nota": "Muestra insuficiente"}

    labs = labels or [str(i) for i in range(len(values))]
    pairs = list(zip(values, labs, strict=True))

    outliers = []
    if method == "iqr":
        s = sorted(clean)
        q1_idx = (n - 1) * 0.25
        q3_idx = (n - 1) * 0.75
        q1 = s[int(q1_idx)] + (q1_idx % 1) * (s[min(int(q1_idx) + 1, n - 1)] - s[int(q1_idx)])
        q3 = s[int(q3_idx)] + (q3_idx % 1) * (s[min(int(q3_idx) + 1, n - 1)] - s[int(q3_idx)])
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        for v, lab in pairs:
            if v is not None and (v < lo or v > hi):
                outliers.append({"label": lab, "value": v, "direction": "high" if v > hi else "low"})
        return {"method": "iqr", "q1": round(q1, 4), "q3": round(q3, 4), "iqr": round(iqr, 4),
                "fence_low": round(lo, 4), "fence_high": round(hi, 4), "outliers": outliers}
    else:  # z-score
        m = mean(clean)
        sd = stdev(clean) if n > 1 else 0
        for v, lab in pairs:
            if v is not None and sd > 0:
                z = abs(v - m) / sd
                if z > 2.5:
                    outliers.append({"label": lab, "value": v, "z_score": round(z, 3)})
        return {"method": "z-score", "mean": round(m, 4), "stddev": round(sd, 4), "threshold": 2.5,
                "outliers": outliers}


# ────────────────────────────────────────────────────────────────── abrupt changes
def detect_abrupt_changes(
    points: list[TimePoint], *, threshold_pct: float = 30.0
) -> list[dict[str, Any]]:
    """Detecta cambios bruscos en una serie temporal (variación > threshold_pct %)."""
    valid = [(p.label, p.value) for p in points if p.value is not None]
    changes = []
    for i in range(1, len(valid)):
        prev_v = valid[i - 1][1]
        curr_v = valid[i][1]
        if prev_v and prev_v != 0:
            pct = abs((curr_v - prev_v) / abs(prev_v) * 100)
            if pct >= threshold_pct:
                changes.append({
                    "from": valid[i - 1][0],
                    "to": valid[i][1],
                    "label_from": valid[i - 1][0],
                    "label_to": valid[i][0],
                    "prev_value": round(prev_v, 4),
                    "curr_value": round(curr_v, 4),
                    "pct_change": round((curr_v - prev_v) / abs(prev_v) * 100, 2),
                    "direction": "up" if curr_v > prev_v else "down",
                })
    return changes
