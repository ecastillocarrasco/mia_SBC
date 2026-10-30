"""Regresiones de anomalías de nómina con metadatos incompletos."""

from pathlib import Path

import pytest

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolStatus
from mia.data import Payslip
from mia.llm import ToolCall
from mia.modules.registry import build_registry
from tests.dbutil import fresh_database
from tests.hr_seed import _emp
from tests.test_domains import NOW


@pytest.mark.parametrize("has_payslip", [False, True])
async def test_employee_without_person_key_can_be_checked(tmp_path: Path, has_payslip: bool) -> None:
    db = await fresh_database(tmp_path, "nominas_anomalies.db")
    try:
        async with db.session() as session:
            session.add(_emp(1, "Persona de prueba", "Cocina", email="persona@example.test"))
            if has_payslip:
                session.add(
                    Payslip(sp_id=1, employee_email="persona@example.test", year=2026, month=8, period="2026-08")
                )
        registry = build_registry(db)
        result = (
            await registry.execute(
                ToolCall("check", "anomalias_nominas", '{"periodo": "2026-08"}'),
                ToolContext(
                    user=UserContext("admin", "Admin", roles=frozenset({"mia.admin"})),
                    request_id=None,
                    now=NOW,
                    session_state={},
                ),
            )
        ).result
        assert result.status is ToolStatus.OK
        assert result.summary["faltantes"] == int(not has_payslip)
        assert result.summary["total_anomalias"] == int(not has_payslip)
        assert isinstance(result.state_updates, dict)
    finally:
        await db.dispose()
