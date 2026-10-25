"""Los tres formatos se generan para cualquier tipo de resultado y se pueden abrir."""

from __future__ import annotations

import io
from datetime import datetime

import pytest
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from mia.modules.rrhh.informes.document import to_document
from mia.modules.rrhh.informes.render import RENDERERS

NOW = datetime(2026, 9, 27, 10, 0)
TABLE = {
    "type": "table",
    "title": "Plantilla",
    "columns": ["Nombre", "Puesto"],
    "rows": [[f"Persona {i}", "Camarera"] for i in range(30)],
}
DASHBOARD = {
    "type": "dashboard",
    "title": "Panel RRHH",
    "kpis": {"plantilla_activa": 651, "trabajando": 139},
    "tables": [TABLE],
}
PROFILE = {
    "type": "employee_360",
    "title": "Ficha 360 · Ana Ruiz",
    "nombre": "Ana Ruiz",
    "hoy": {"turno": {"tipo": "Trabajo", "horario": "7:00-15:00"}, "ausencia_en_curso": None},
    "semana_actual": [{"fecha": "2026-09-21", "tipo": "Trabajo", "horario": "7-15"}],
    "vacaciones": {"saldo_actual": -2.5, "pendientes": 1},
    "indicadores": {"saldo_vacaciones": -2.5, "documentos_firmados": 3},
    "acciones_rapidas": ["Muéstrame sus turnos"],
}


@pytest.mark.parametrize("presentation", [TABLE, DASHBOARD, PROFILE], ids=["tabla", "panel", "ficha360"])
@pytest.mark.parametrize("fmt", ["pdf", "xlsx", "pptx", "docx"])
def test_every_result_renders_in_every_format(presentation: dict[str, object], fmt: str) -> None:
    doc = to_document(presentation)
    content = RENDERERS[fmt](doc, NOW, None)
    if fmt == "pdf":
        text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
        assert doc.title.split(" · ")[0] in text
    elif fmt == "xlsx":
        assert load_workbook(io.BytesIO(content)).sheetnames
    elif fmt == "docx":
        from docx import Document as WordDocument  # noqa: PLC0415

        word = WordDocument(io.BytesIO(content))
        assert doc.title.split(" · ")[0] in "\n".join(p.text for p in word.paragraphs)
    else:
        slides = Presentation(io.BytesIO(content)).slides
        assert len(slides) >= 2


def test_profile_sections_become_blocks() -> None:
    doc = to_document(PROFILE)
    titles = [b.title for b in doc.blocks]
    assert titles[0] == "Indicadores" and "Semana actual" in titles and "Ficha laboral" in titles
    assert "Acciones rapidas" not in " ".join(titles)
    flat = " ".join(str(v) for b in doc.blocks for v in b.data.values())
    assert "Empleado id" not in flat and "sin_incidencias" not in flat  # nada técnico en la ficha


def test_numbers_are_formatted_in_spanish_in_reports() -> None:
    from mia.modules.rrhh.informes.document import format_number  # noqa: PLC0415

    assert [format_number(v) for v in (0.0, 24.0, 2.5, 1234.5, 343)] == ["0", "24", "2,5", "1.234,5", "343"]


def test_profile_indicators_have_no_decimal_noise() -> None:
    """Caso real: el PDF de la ficha mostraba «0.0» de saldo y «24.0» de saldo total."""
    doc = to_document(
        {
            **PROFILE,
            "type": "employee_360",
            "indicadores": {"saldo_vacaciones": 0.0},
            "vacaciones": {"saldo_total": 24.0},
        }
    )
    kpis = next(b for b in doc.blocks if b.kind == "kpis")
    assert list(kpis.data.values()) == ["0"]
    vac = next(b for b in doc.blocks if b.title == "Vacaciones")
    assert vac.data["Saldo total"] == "24"
