"""The supervised indexer must reject changed code and disabled privacy guards."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from tools import mia_index_lote_controlado as controlled
from tools import mia_indexacion_supervisada as supervisor


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_audited_indexer_accepts_git_line_endings_but_keeps_sensitive_guard(tmp_path, newline):
    source = Path(controlled.__file__).read_bytes().replace(b"\r\n", b"\n")
    script = tmp_path / "indexer.py"
    script.write_bytes(source.replace(b"\n", newline))
    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://test:test@localhost:5432/mia",
        privacy_gateway=SimpleNamespace(
            enabled=True,
            fail_open=False,
            vault_key=SimpleNamespace(get_secret_value=lambda: "synthetic-test-key"),
        ),
        data=SimpleNamespace(index_sensitive_content=False),
    )
    with pytest.raises(supervisor.SafetyStop, match="Indexacion sensible no activada"):
        supervisor.validate_config(settings, script)


def test_supervisor_rejects_modified_indexer_before_database_or_credentials(tmp_path):
    script = tmp_path / "indexer.py"
    script.write_bytes(Path(controlled.__file__).read_bytes() + b"\nraise RuntimeError('changed')\n")
    with pytest.raises(supervisor.SafetyStop, match="difiere de la version auditada"):
        supervisor.validate_config(None, script)


async def test_controlled_indexer_cannot_open_database_when_sensitive_indexing_is_disabled(monkeypatch):
    monkeypatch.setattr(
        controlled,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql+asyncpg://test:test@localhost:5432/mia",
            data=SimpleNamespace(index_sensitive_content=False),
        ),
    )

    def forbidden_database(*args, **kwargs):
        pytest.fail("A blocked indexing request must not connect to the database")

    monkeypatch.setattr(controlled, "Database", forbidden_database)
    assert await controlled._run("nominas", 1, True) == 2
