"""Las migraciones crean exactamente el esquema de los modelos."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from mia.data import Base

ROOT = Path(__file__).resolve().parents[1]


def _config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_upgrade_matches_models(tmp_path: Path) -> None:
    db_file = tmp_path / "mig.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db_file}"), "head")
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_postgres_ddl_renders(capsys: object) -> None:
    command.upgrade(_config("postgresql+asyncpg://u:p@localhost/db"), "head", sql=True)
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "CREATE TABLE conversation_sessions" in out
    assert "JSONB" in out


def test_downgrade_is_clean(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'down.db'}"
    command.upgrade(_config(url), "head")
    command.downgrade(_config(url), "base")
    engine = create_engine(f"sqlite:///{tmp_path / 'down.db'}")
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert tables == {"alembic_version"}


def test_expected_revision_matches_the_latest_migration() -> None:
    """mIA avisa de migraciones pendientes comparando con esta revisión: debe ser siempre la última."""
    from alembic.config import Config  # noqa: PLC0415
    from alembic.script import ScriptDirectory  # noqa: PLC0415

    from mia.data.schema import EXPECTED_REVISION  # noqa: PLC0415

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    assert ScriptDirectory.from_config(config).get_current_head() == EXPECTED_REVISION


async def test_pending_migrations_are_reported_clearly(tmp_path: Path) -> None:
    """Caso real: PostgreSQL en la 0006 y el código en la 0007 daba «no existe la columna extra» en plena sincronización."""
    from sqlalchemy import text  # noqa: PLC0415

    from mia.data.schema import EXPECTED_REVISION, schema_problem  # noqa: PLC0415
    from tests.dbutil import fresh_database  # noqa: PLC0415

    db = await fresh_database(tmp_path, "versiones.db")
    async with db.session() as s:  # en PostgreSQL la base de pruebas es compartida: partir siempre de cero
        await s.execute(text("DROP TABLE IF EXISTS alembic_version"))
    assert await schema_problem(db) is None  # sin tabla de versiones no se puede saber: no se avisa
    async with db.session() as s:
        await s.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await s.execute(text("INSERT INTO alembic_version VALUES ('0006')"))
    problem = await schema_problem(db)
    assert problem and "0006" in problem and "alembic upgrade head" in problem
    async with db.session() as s:
        await s.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": EXPECTED_REVISION})
    assert await schema_problem(db) is None
    async with db.session() as s:
        await s.execute(text("DROP TABLE alembic_version"))  # no dejar rastro para otros tests
    await db.dispose()
