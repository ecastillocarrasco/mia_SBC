"""PeriodEngine — expresiones naturales de tiempo → (fecha_inicio, fecha_fin).

Cubre las expresiones más habituales en consultas de RRHH:
  "hoy", "ayer", "esta semana", "mes pasado", "últimos 3 meses",
  "Q2", "YTD", "2025", "desde enero hasta marzo", "verano"…

El resultado siempre es un par (date, date) con start <= end.
El engine es stateless: se pasa la fecha de referencia en cada llamada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class ResolvedPeriod:
    start: date
    end: date
    label: str
    """Etiqueta legible para mostrar al usuario («octubre 2026», «Q3 2026»…)."""

    def __contains__(self, d: date) -> bool:
        return self.start <= d <= self.end


_MONTH_ES: dict[str, int] = {
    "enero": 1, "ene": 1,
    "febrero": 2, "feb": 2,
    "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6,
    "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "septiembre": 9, "sep": 9, "sept": 9,
    "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}

_QUARTER_MONTHS: dict[int, tuple[int, int]] = {
    1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)
}

_SEASON_ES: dict[str, tuple[int, int]] = {
    "verano": (6, 8),
    "otono": (9, 11),
    "otoño": (9, 11),
    "invierno": (12, 2),
    "primavera": (3, 5),
    "temporada alta": (6, 9),
    "temporada baja": (10, 5),
}


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def _quarter_period(year: int, q: int, ref: date) -> ResolvedPeriod:
    sm, em = _QUARTER_MONTHS[q]
    start = date(year, sm, 1)
    end = _month_end(year, em)
    end = min(end, ref)
    return ResolvedPeriod(start, end, f"Q{q} {year}")


def _normalize(text: str) -> str:
    return (
        text.lower()
        .strip()
        .replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    )


class PeriodEngine:
    """Convierte expresiones naturales en fechas absolutas.

    Uso::

        pe = PeriodEngine()
        period = pe.resolve("últimos 3 meses", today=date.today())
        # ResolvedPeriod(start=date(2026,7,6), end=date(2026,10,6), label="últimos 3 meses")
    """

    def resolve(self, expression: str, today: date | None = None) -> ResolvedPeriod | None:
        """Devuelve (start, end) o None si la expresión no se reconoce."""
        ref = today or date.today()
        norm = _normalize(expression)
        return (
            self._exact(norm, ref)
            or self._relative_days(norm, ref)
            or self._relative_months(norm, ref)
            or self._ytd(norm, ref)
            or self._quarter(norm, ref)
            or self._year(norm, ref)
            or self._named_month(norm, ref)
            or self._season(norm, ref)
            or self._from_to(norm, ref)
        )

    # ------------------------------------------------------------------ patrones
    def _exact(self, n: str, ref: date) -> ResolvedPeriod | None:
        if n in ("hoy", "today"):
            return ResolvedPeriod(ref, ref, "hoy")
        if n in ("ayer", "yesterday"):
            d = ref - timedelta(days=1)
            return ResolvedPeriod(d, d, "ayer")
        if n in ("manana", "mañana", "tomorrow"):
            d = ref + timedelta(days=1)
            return ResolvedPeriod(d, d, "mañana")
        if n in ("esta semana", "semana actual"):
            monday = ref - timedelta(days=ref.weekday())
            sunday = monday + timedelta(days=6)
            return ResolvedPeriod(monday, min(sunday, ref), "esta semana")
        if n in ("semana pasada", "la semana pasada"):
            monday = ref - timedelta(days=ref.weekday() + 7)
            sunday = monday + timedelta(days=6)
            return ResolvedPeriod(monday, sunday, "semana pasada")
        if n in ("este mes", "mes actual", "el mes actual"):
            start = ref.replace(day=1)
            return ResolvedPeriod(start, ref, f"{ref.strftime('%B %Y')}")
        if n in ("mes pasado", "el mes pasado", "mes anterior"):
            first_this = ref.replace(day=1)
            last_month = first_this - timedelta(days=1)
            start = last_month.replace(day=1)
            return ResolvedPeriod(start, last_month, f"{last_month.strftime('%B %Y')}")
        if n in ("este ano", "este año", "el ano actual", "el año actual"):
            start = ref.replace(month=1, day=1)
            return ResolvedPeriod(start, ref, str(ref.year))
        if n in ("ano pasado", "año pasado", "el ano pasado", "el año pasado", "año anterior"):
            year = ref.year - 1
            return ResolvedPeriod(date(year, 1, 1), date(year, 12, 31), str(year))
        return None

    def _relative_days(self, n: str, ref: date) -> ResolvedPeriod | None:
        m = re.match(r"ultimos?\s+(\d+)\s+dias?", n)
        if not m:
            m = re.match(r"(?:en\s+los?\s+)?(?:ultimos?|pasados?)\s+(\d+)\s+dias?", n)
        if m:
            days = int(m.group(1))
            start = ref - timedelta(days=days - 1)
            return ResolvedPeriod(start, ref, f"últimos {days} días")
        return None

    def _relative_months(self, n: str, ref: date) -> ResolvedPeriod | None:
        m = re.match(r"(?:ultimos?|pasados?)\s+(\d+)\s+meses?", n)
        if not m:
            m = re.match(r"(?:en\s+los?\s+)?(?:ultimos?|pasados?)\s+(\d+)\s+meses?", n)
        if m:
            months = int(m.group(1))
            # start = same day N months ago (approximate)
            total_months = ref.month - months
            year_offset = (total_months - 1) // 12 if total_months <= 0 else 0
            month = ((total_months - 1) % 12) + 1 if total_months <= 0 else total_months
            year = ref.year + year_offset if total_months <= 0 else ref.year
            try:
                start = date(year, month, ref.day)
            except ValueError:
                start = _month_end(year, month)
            return ResolvedPeriod(start, ref, f"últimos {months} meses")
        return None

    def _ytd(self, n: str, ref: date) -> ResolvedPeriod | None:
        if n in ("ytd", "year to date", "acumulado del ano", "acumulado del año", "desde inicio de ano",
                 "desde inicio de año", "desde enero", "lo que llevamos de ano", "lo que llevamos de año"):
            start = ref.replace(month=1, day=1)
            return ResolvedPeriod(start, ref, f"YTD {ref.year}")
        return None

    def _quarter(self, n: str, ref: date) -> ResolvedPeriod | None:
        # "Q1", "q2", "primer trimestre", "tercer trimestre 2025"
        m = re.match(r"q([1-4])(?:\s+(\d{4}))?", n)
        if m:
            q = int(m.group(1))
            year = int(m.group(2)) if m.group(2) else ref.year
            return _quarter_period(year, q, ref)
        spanish_q = {"primer": 1, "primero": 1, "segundo": 2, "tercer": 3, "tercero": 3, "cuarto": 4}
        m2 = re.match(r"(primer|primero|segundo|tercer|tercero|cuarto)\s+trimestre(?:\s+(?:de\s+)?(\d{4}))?", n)
        if m2:
            q = spanish_q[m2.group(1)]
            year = int(m2.group(2)) if m2.group(2) else ref.year
            return _quarter_period(year, q, ref)
        if n in ("trimestre actual", "este trimestre"):
            q = (ref.month - 1) // 3 + 1
            return _quarter_period(ref.year, q, ref)
        if n in ("trimestre pasado", "trimestre anterior"):
            q = (ref.month - 1) // 3 + 1
            q -= 1
            year = ref.year
            if q < 1:
                q = 4
                year -= 1
            sm, em = _QUARTER_MONTHS[q]
            return ResolvedPeriod(date(year, sm, 1), _month_end(year, em), f"Q{q} {year}")
        return None

    def _year(self, n: str, ref: date) -> ResolvedPeriod | None:
        m = re.fullmatch(r"(\d{4})", n)
        if m:
            year = int(m.group(1))
            if 1990 <= year <= ref.year + 1:
                end = date(year, 12, 31) if year < ref.year else ref
                return ResolvedPeriod(date(year, 1, 1), end, str(year))
        return None

    def _named_month(self, n: str, ref: date) -> ResolvedPeriod | None:
        # "enero", "febrero 2025", "octubre del año pasado"
        for month_name, month_num in _MONTH_ES.items():
            # "mes [de] [año]"
            m = re.match(rf"^{re.escape(month_name)}(?:\s+(?:de\s+)?(\d{{4}}))?$", n)
            if m:
                year = int(m.group(1)) if m.group(1) else ref.year
                start = date(year, month_num, 1)
                end = _month_end(year, month_num)
                end = min(end, ref)
                return ResolvedPeriod(start, end, f"{month_name.capitalize()} {year}")
        return None

    def _season(self, n: str, ref: date) -> ResolvedPeriod | None:
        for name, (sm, em) in _SEASON_ES.items():
            if name in n:
                year = ref.year
                if sm > em:  # invierno: dic–feb
                    start = date(year, sm, 1)
                    end = _month_end(year + 1, em)
                else:
                    start = date(year, sm, 1)
                    end = _month_end(year, em)
                end = min(end, ref)
                return ResolvedPeriod(start, end, name.capitalize())
        return None

    def _from_to(self, n: str, ref: date) -> ResolvedPeriod | None:
        # "desde enero hasta marzo", "de enero a junio", "entre enero y junio"
        sep = re.search(r"\s+(?:hasta|a|y)\s+", n)
        if not sep:
            return None
        prefix = n[: sep.start()]
        suffix = n[sep.end():]
        # strip "desde"/"de"/"entre"
        prefix = re.sub(r"^(desde|de|entre)\s+", "", prefix).strip()
        start_p = self.resolve(prefix, ref)
        end_p = self.resolve(suffix, ref)
        if start_p and end_p:
            return ResolvedPeriod(start_p.start, end_p.end, f"{prefix} – {suffix}")
        return None


period_engine = PeriodEngine()
