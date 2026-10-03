"""SQLite no aplica la longitud de VARCHAR y PostgreSQL sí: estos tests evitan que
un valor válido reviente solo en producción (fallo real: «invalid_arguments» en VARCHAR(16))."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import String

from mia.conversation import AvatarState, ToolStatus
from mia.data import AuditEvent, ConversationTurn, ShiftDay, SourceSyncState
from mia.sources import all_sources
from mia.sources.mappers.hr import ShiftKind


def _length(column: Any) -> int:
    col_type = column.property.columns[0].type
    assert isinstance(col_type, String) and col_type.length
    return int(col_type.length)


@pytest.mark.parametrize(
    ("column", "values"),
    [
        (AuditEvent.outcome, [s.value for s in ToolStatus]),
        (ConversationTurn.avatar_state, [s.value for s in AvatarState]),
        (ConversationTurn.role, ["user", "assistant"]),
        (SourceSyncState.status, ["never", "ok", "error"]),
        (SourceSyncState.source, [s.key for s in all_sources()]),
        (ShiftDay.kind, [v for k, v in vars(ShiftKind).items() if not k.startswith("_")]),
    ],
)
def test_enumerated_values_fit_their_columns(column: Any, values: list[str]) -> None:
    limit = _length(column)
    too_long = [v for v in values if len(v) > limit]
    assert not too_long, f"{column} admite {limit} caracteres: {too_long}"


def test_audit_action_fits_every_tool_name() -> None:
    from mia.data import Database  # noqa: PLC0415
    from mia.modules.rrhh import build_registry  # noqa: PLC0415

    registry = build_registry(Database("sqlite+aiosqlite:///:memory:"))
    limit = _length(AuditEvent.action)
    assert all(len(f"tool:{name}") <= limit for name in registry.names())
