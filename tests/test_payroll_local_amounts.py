"""Version-checked local text must match original financial calculations or read the PDF."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from mia.data import HrDocumentText, Payslip
from mia.modules.rrhh.common import Deps
from mia.modules.rrhh.nominas import analisis_economico as economic
from mia.modules.rrhh.nominas.estadisticas import amount_values
from mia.modules.rrhh.nominas.parser import parse_payslip
from tests.dbutil import fresh_database
from tests.test_analisis_economico import _payslip_text


def sample():
    return _payslip_text(1500) + (
        "APORTACIÓN EMPRESA\n"
        "Contingencias Comunes 1.830,15 23,60 % 431,92\n"
        "Accidentes de trabajo 1.830,15 1,50 % 27,45\n"
    )


def test_normalized_index_text_retains_the_same_net_gross_and_all_employer_contributions():
    original = amount_values(parse_payslip(sample()))
    normalized = amount_values(parse_payslip(" ".join(sample().split())))
    assert original == normalized
    assert normalized["liquido"] == 1500
    assert normalized["coste_empresa_ss"] == pytest.approx(459.37)
    assert normalized["coste_total_empresa"] == pytest.approx(2289.52)


@pytest.mark.parametrize("columns", [3, 4, 5, 6])
def test_empty_base_columns_require_explicit_net_to_validate_the_two_final_totals(columns):
    lines = sample().splitlines()
    values = ["100,00"] * (columns - 2) + ["1.830,15", "330,15"]
    lines[3] = " ".join(values)
    text = " ".join("\n".join(lines).split())
    parsed = parse_payslip(text)
    assert parsed["comprobacion"]["cuadra"]
    assert parsed["importes"]["total_devengado"] == 1830.15
    assert "base_cotizacion_cc" not in parsed["importes"]
    assert amount_values(parsed)["coste_total_empresa"] == pytest.approx(2289.52)
    inconsistent = parse_payslip(text.replace("1.500,00", "1.400,00"))
    assert "total_devengado" not in inconsistent["importes"]
    missing_net = parse_payslip(text.replace("1.500,00 Líquido a percibir", ""))
    assert "total_devengado" not in missing_net["importes"]


@pytest.mark.parametrize(
    "invalid", [None, "revision", "unknown_revision", "owner", "domain", "status", "inconsistent", "disabled"]
)
async def test_local_reuse_requires_same_source_version_owner_domain_and_valid_calculation(
    tmp_path, monkeypatch, invalid
):
    db = await fresh_database(tmp_path)
    revision = datetime(2026, 1, 1, tzinfo=UTC)
    slip = Payslip(sp_id=1, person_key="synthetic-person", period="2026-01", modified_at=revision, special=False)
    text = " ".join(sample().split())
    if invalid == "inconsistent":
        text = text.replace("1.500,00", "1.400,00")
    indexed = HrDocumentText(
        domain="documentos_firmados" if invalid == "domain" else "nominas",
        document_id=1,
        person_key="other-person" if invalid == "owner" else "synthetic-person",
        source_modified=None
        if invalid == "unknown_revision"
        else revision + timedelta(days=1 if invalid == "revision" else 0),
        status="error" if invalid == "status" else "ok",
        text=text,
    )
    async with db.session() as session:
        session.add_all([slip, indexed])
    deps = Deps(db, settings=SimpleNamespace(data=SimpleNamespace(index_sensitive_content=invalid != "disabled")))
    downloads = []

    async def read_original(deps, slip_id, gate):
        downloads.append(slip_id)
        return {"liquido": 42.0}

    monkeypatch.setattr(economic, "_amounts", read_original)
    try:
        result = await economic._fetch_amounts_batch(
            deps, [slip], asyncio.Semaphore(2), required_key="coste_total_empresa"
        )
        if invalid is None:
            assert downloads == []
            assert result[1]["coste_total_empresa"] == pytest.approx(2289.52)
        else:
            assert downloads == [1]
            assert result[1] == {"liquido": 42.0}
    finally:
        await db.dispose()
