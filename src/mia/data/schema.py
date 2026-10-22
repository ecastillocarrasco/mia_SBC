"""Versión del esquema que espera este código: si la base de datos va por detrás, hay que aplicar las migraciones."""

from __future__ import annotations

from sqlalchemy import text

from mia.data.db import Database

EXPECTED_REVISION = "0013"
"""Última migración de Alembic (migrations/versions). Un test comprueba que coincide con la real."""


async def current_revision(db: Database) -> str | None:
    async with db.session() as session:
        try:
            return (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
        except Exception:  # la tabla no existe: base sin migrar
            return None


async def schema_problem(db: Database) -> str | None:
    """Texto claro si faltan migraciones (o None si todo está al día)."""
    found = await current_revision(db)
    if found is None or found == EXPECTED_REVISION:
        return None  # sin tabla de versiones (bases creadas sin Alembic, p. ej. pruebas) no se puede saber
    return (
        f"La base de datos está en la revisión {found} y este código espera la {EXPECTED_REVISION}. "
        "Aplica las migraciones pendientes con:  alembic upgrade head"
    )
