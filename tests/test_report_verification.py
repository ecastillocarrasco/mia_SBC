from datetime import UTC, datetime

import pytest

from mia.modules.rrhh.informes.persist import render_document
from mia.reporting.document import Block, Document
from mia.reporting.verification import ReportVerificationError, verify_artifact, verify_document


@pytest.mark.parametrize("fmt", ["pdf", "xlsx", "pptx", "html", "docx"])
def test_actual_artifact_contains_every_original_table_cell(fmt):
    document = Document(
        "Informe verificable",
        [
            Block(
                "table",
                "Población",
                {
                    "columns": ["Persona", "Importe"],
                    "rows": [["Persona sintética Alfa", "1.234,56 €"], ["Persona sintética Beta", "2.345,67 €"]],
                },
            )
        ],
    )
    content = render_document(fmt, document, datetime.now(UTC), None)
    verify_artifact(fmt, content, document)
    changed = Document(
        "Informe verificable",
        [
            Block(
                "table",
                "Población",
                {
                    "columns": ["Persona", "Importe"],
                    "rows": [["Persona sintética Gamma", "9.876,54 €"]],
                },
            )
        ],
    )
    with pytest.raises(ReportVerificationError):
        verify_artifact(fmt, content, changed)


@pytest.mark.parametrize("fmt", ["xlsx", "docx", "pptx"])
def test_same_numbers_assigned_to_different_people_are_rejected(fmt):
    original = Document(
        "Asociaciones",
        [
            Block(
                "table",
                "Datos",
                {
                    "columns": ["Persona", "Importe"],
                    "rows": [["Alfa", "1.234,50 €"], ["Beta", "2.345,60 €"]],
                },
            )
        ],
    )
    content = render_document(fmt, original, datetime.now(UTC), None)
    swapped = Document(
        "Asociaciones",
        [
            Block(
                "table",
                "Datos",
                {
                    "columns": ["Persona", "Importe"],
                    "rows": [["Alfa", "2.345,60 €"], ["Beta", "1.234,50 €"]],
                },
            )
        ],
    )
    with pytest.raises(ReportVerificationError, match="asociación"):
        verify_artifact(fmt, content, swapped)


@pytest.mark.parametrize("fmt", ["pdf", "xlsx", "docx", "pptx", "html"])
def test_report_indicator_is_checked_in_the_actual_file(fmt):
    original = Document("Indicadores", [Block("kpis", "Resumen", {"Coste": "1.234,50 €"})])
    content = render_document(fmt, original, datetime.now(UTC), None)
    changed = Document("Indicadores", [Block("kpis", "Resumen", {"Coste": "9.876,50 €"})])
    with pytest.raises(ReportVerificationError, match="indicador"):
        verify_artifact(fmt, content, changed)


def test_corrupt_file_and_inconsistent_charts_are_blocked():
    document = Document("Informe", [Block("table", "Datos", {"columns": ["A"], "rows": [["valor"]]})])
    with pytest.raises(ReportVerificationError):
        verify_artifact("xlsx", b"archivo corrupto", document)
    with pytest.raises(ReportVerificationError):
        verify_document(
            Document("Gráfico", [Block("chart", "Datos", {"labels": ["A", "B"], "series": [{"values": [1]}]})])
        )


@pytest.mark.parametrize("fmt", ["xlsx", "docx", "pptx"])
def test_integral_floats_keep_their_numeric_value_and_columns(fmt):
    original = Document(
        "Decimales",
        [
            Block(
                "table",
                "Datos",
                {
                    "columns": ["Persona", "Horas", "Vacío", "Extra"],
                    "rows": [["Alfa", 6.0, None, 0.0]],
                },
            )
        ],
    )
    content = render_document(fmt, original, datetime.now(UTC), None)
    verify_artifact(fmt, content, original)
    for changed_row in (["Alfa", 60.0, None, 0.0], ["Alfa", None, 6.0, 0.0]):
        changed = Document(
            "Decimales",
            [
                Block(
                    "table",
                    "Datos",
                    {
                        "columns": ["Persona", "Horas", "Vacío", "Extra"],
                        "rows": [changed_row],
                    },
                )
            ],
        )
        with pytest.raises(ReportVerificationError, match="asociación"):
            verify_artifact(fmt, content, changed)


def test_pptx_continuations_preserve_the_complete_row_across_slides():
    note = "Protección de datos: grupo inferior al mínimo autorizado. " * 12
    columns = ["Persona", "Cantidad", "Nota", "A", "B", "C"]
    original = Document(
        "Continuaciones",
        [
            Block(
                "table",
                "Datos",
                {
                    "columns": columns,
                    "rows": [["Alfa", 2, note, None, None, None]],
                },
            )
        ],
    )
    content = render_document("pptx", original, datetime.now(UTC), None)
    verify_artifact("pptx", content, original)
    for changed_row in (["Beta", 2, note, None, None, None], ["Alfa", 2, note + "Omitido", None, None, None]):
        changed = Document("Continuaciones", [Block("table", "Datos", {"columns": columns, "rows": [changed_row]})])
        with pytest.raises(ReportVerificationError, match="asociación"):
            verify_artifact("pptx", content, changed)


def test_xlsx_percentage_serialization_preserves_the_value():
    columns = ["Persona", "Peso"]
    original = Document(
        "Porcentajes",
        [
            Block(
                "table",
                "Datos",
                {
                    "columns": columns,
                    "rows": [["Alfa", "32.9%"], ["Beta", "29.1%"]],
                },
            )
        ],
    )
    content = render_document("xlsx", original, datetime.now(UTC), None)
    verify_artifact("xlsx", content, original)
    changed = Document(
        "Porcentajes",
        [
            Block(
                "table",
                "Datos",
                {
                    "columns": columns,
                    "rows": [["Alfa", "32.8%"], ["Beta", "29.1%"]],
                },
            )
        ],
    )
    with pytest.raises(ReportVerificationError, match="asociación"):
        verify_artifact("xlsx", content, changed)
