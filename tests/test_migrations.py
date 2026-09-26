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
