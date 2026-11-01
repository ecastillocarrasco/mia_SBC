"""Reuse source-version-matched local payroll text without external model calls.

Amounts are calculated transiently with the same parser as PDFs. No new amounts are persisted.
Unknown versions, changed ownership, incomplete or inconsistent text fall back to the original PDF.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from mia.data import HrDocumentText, Payslip
from mia.modules.rrhh.common import Deps
from mia.modules.rrhh.nominas.estadisticas import amount_values
from mia.modules.rrhh.nominas.parser import parse_payslip


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_rows(
    rows: list[HrDocumentText], expected: dict[int, Payslip], required_key: str | None
) -> dict[int, dict[str, float]]:
    found = {}
    for row in rows:
        slip = expected[row.document_id]
        if not row.source_modified or not slip.modified_at or _utc(row.source_modified) != _utc(slip.modified_at):
            continue
        if not slip.person_key or row.person_key != slip.person_key or not row.text:
            continue
        parsed = parse_payslip(row.text)
        if not (parsed.get("comprobacion") or {}).get("cuadra"):
            continue
        values = amount_values(parsed)
        if not values:
            continue
        if required_key == "coste_total_empresa" and required_key not in values and "APORTACI" in row.text.upper():
            continue
        found[row.document_id] = values
    return found


async def indexed_amounts(
    deps: Deps, payslips: list[Payslip], *, required_key: str | None = None
) -> dict[int, dict[str, float]]:
    if not getattr(getattr(deps.settings, "data", None), "index_sensitive_content", False):
        return {}
    expected = {slip.sp_id: slip for slip in payslips}
    ids = list(expected)
    found = {}
    for start in range(0, len(ids), 400):
        async with deps.db.session() as session:
            rows = list(
                (
                    await session.scalars(
                        select(HrDocumentText).where(
                            HrDocumentText.domain == "nominas",
                            HrDocumentText.status == "ok",
                            HrDocumentText.document_id.in_(ids[start : start + 400]),
                        )
                    )
                ).all()
            )
        found.update(await asyncio.to_thread(_parse_rows, rows, expected, required_key))
    return found
