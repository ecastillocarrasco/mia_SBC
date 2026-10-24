"""Fase 4b: analítica, ETT, importes de nómina y lectura de documentos."""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from reportlab.pdfgen import canvas

from mia.auth import UserContext
from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.conversation import ToolContext, ToolRegistry, ToolStatus
from mia.data import Database, Payslip, SignedDocument, TtRate, TtTimesheet
from mia.llm import ToolCall
from mia.modules.registry import build_registry
from mia.modules.rrhh.nominas.parser import parse_payslip
from tests.dbutil import fresh_database
from tests.hr_seed import seed
from tests.test_domains import NOW

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
MANAGER = UserContext("m", "Responsable", roles=frozenset({"mia.responsable"}))

PAYSLIP_TEXT = """EMPRESA SUNSET BEACH CLUB
Mensual - Agosto 2026
REM. TOTAL P.P. EXTRAS BASE C.C. BASE A.T. Y DES BASE I.R.P.F. T. DEVENGADO T. A DEDUCIR
1.600,00 266,67 1.866,67 1.866,67 1.866,67 1.866,67 330,15
Tributación I.R.P.F. (11,50 %) 214,67
1.536,52 Líquido a percibir
"""


def _pdf(text: str) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 800
    for line in text.splitlines():
        pdf.drawString(40, y, line)
        y -= 16
    pdf.save()
    return buffer.getvalue()


def test_payslip_parser_reads_summary_and_checks_it() -> None:
    parsed = parse_payslip(PAYSLIP_TEXT)
    amounts = parsed["importes"]
    assert amounts["total_devengado"] == 1866.67 and amounts["total_deducciones"] == 330.15
    assert amounts["liquido"] == 1536.52 and amounts["irpf_porcentaje"] == 11.5
    assert parsed["comprobacion"] == {"cuadra": True, "diferencia": 0.0}


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[tuple[ToolRegistry, Database]]:
    db = await fresh_database(tmp_path, "p4b.db")
    await seed(db)
    async with db.session() as s:
        s.add_all(
            [
                Payslip(sp_id=501, person_key="pk-ana", year=2026, month=7, period="2026-07", special=False),
                SignedDocument(sp_id=601, person_key="pk-ana", doc_type="Contrato", file_name="Contrato_2024.pdf"),
                TtRate(
                    sp_id=1,
                    company="ETT Uno",
                    company_key="ett uno",
                    price_normal=15.0,
                    price_night=18.0,
                    price_diet=10.0,
                    short_contract_surcharge=10.0,
                ),
                TtTimesheet(
                    sp_id=9,
                    day=date(2026, 8, 3),
                    worker_name="Leo",
                    company="ETT Uno",
                    hours_total=14,
                    hours_normal=14,
                    amount=210.0,
                ),
            ]
        )

    def files(request: httpx.Request) -> httpx.Response:
        if "items(501)/File" in request.url.path:
            return httpx.Response(200, content=_pdf(PAYSLIP_TEXT))
        if "items(601)/File" in request.url.path:
            return httpx.Response(200, content=_pdf("CONTRATO DE TRABAJO\nJornada de 40 horas semanales."))
        return httpx.Response(404)

    sp = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files)
    )
    yield build_registry(db, sharepoint=sp), db
    await sp.aclose()
    await db.dispose()


async def call(registry: ToolRegistry, name: str, user: UserContext = ADMIN, **args: Any) -> Any:
    ctx = ToolContext(user=user, request_id=None, now=NOW, session_state={})
    return (await registry.execute(ToolCall("c", name, json.dumps(args)), ctx)).result


async def test_payslip_amounts_are_read_on_demand(env: Any) -> None:
    registry, _ = env
    result = await call(registry, "nomina_importes", empleado_id=1)
    slip = result.summary["nominas"][0]
    assert slip["periodo"] == "2026-07" and slip["importes"]["liquido"] == 1536.52


async def test_payslip_amounts_need_their_own_permission(env: Any) -> None:
    registry, _ = env
    rrhh_reader = UserContext("r", "Lectura", roles=frozenset({"mia.responsable"}))
    assert (await call(registry, "nomina_importes", rrhh_reader, empleado_id=1)).status is ToolStatus.PERMISSION_DENIED


async def test_document_content_is_read(env: Any) -> None:
    registry, _ = env
    result = await call(registry, "leer_documento", empleado_id=1, tipo="contrato")
    assert "40 horas" in result.summary["texto"]


async def test_hr_panel_and_comparison(env: Any) -> None:
    registry, _ = env
    panel = await call(registry, "panel_rrhh")
    kpis = panel.summary["indicadores"]
    assert kpis["plantilla_activa"] == 3 and kpis["bajas_en_curso"] == 1 and kpis["vacaciones_en_curso"] == 1
    assert panel.presentation["type"] == "dashboard"
    comparison = await call(registry, "comparar_departamentos", departamentos=["pisos", "cocina"])
    assert set(comparison.summary["comparativa"]) == {"Pisos", "Cocina"}


async def test_weekly_coverage_and_vacation_analytics(env: Any) -> None:
    registry, _ = env
    coverage = await call(registry, "cobertura_semanal")
    assert len(coverage.summary["dias"]) == 7
    analytics = await call(registry, "analitica_vacaciones", anio=2026)
    assert analytics.summary["dias_persona_por_mes"]["ago"] > 0


async def test_data_quality_is_admin_only(env: Any) -> None:
    registry, _ = env
    assert (await call(registry, "calidad_datos", MANAGER)).status is ToolStatus.PERMISSION_DENIED
    quality = await call(registry, "calidad_datos")
    assert quality.summary["sin_email"] == 0 and quality.summary["plantilla_activa"] == 3


async def test_temporary_work_cost_and_anomalies(env: Any) -> None:
    registry, _ = env
    cost = await call(
        registry,
        "estimar_coste_tt",
        empresa="ett uno",
        horas_normales=10,
        horas_nocturnas=2,
        aplicar_recargo_corta_duracion=True,
    )
    assert cost.summary["coste_base"] == 186.0 and cost.summary["coste_estimado"] == 204.6
    anomalies = await call(registry, "anomalias_tt", desde="2026-08-01", hasta="2026-08-31")
    assert anomalies.summary["con_anomalias"] == 1
    assert "más de 12 horas" in anomalies.summary["anomalias"][0]["motivos"][0]


async def test_document_master_comparison(env: Any) -> None:
    registry, db = env
    from mia.data import DocumentTypeConfig  # noqa: PLC0415

    async with db.session() as s:
        s.add_all(
            [
                DocumentTypeConfig(
                    site="rrhh", sp_id=1, name="LOPD", name_key="lopd", sign_all=True, requires_authorization=False
                ),
                DocumentTypeConfig(site="portal", sp_id=1, name="LOPD", name_key="lopd", requires_authorization=True),
                DocumentTypeConfig(site="rrhh", sp_id=2, name="PRL", name_key="prl", sign_all=False),
            ]
        )
    result = await call(registry, "maestros_documentales")
    assert result.summary["solo_en_rrhh"] == ["PRL"]
    lopd = next(t for t in result.summary["tipos"] if t["tipo"] == "LOPD")
    assert lopd["firmar_todas"] is True and lopd["autorizacion_coincide"] is False
    mandatory = await call(registry, "documentos_faltantes")
    assert mandatory.summary["tipo"] == "obligatorios (FirmarTodas)"
