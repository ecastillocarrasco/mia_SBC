"""Valida la forma de los ficheros de prompts de evaluación en tests/evals/.

No ejecuta los prompts contra el LLM (eso requiere credenciales reales); solo
garantiza que el banco de evaluación es consistente y que se mantiene por
encima del umbral mínimo de cobertura acordado (>=1000 prompts, ver
CLAUDE.md / especificación de expansión funcional).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

EVALS_DIR = Path(__file__).parent
MIN_TOTAL_PROMPTS = 1000

KNOWN_DOMAINS = {
    "empleados",
    "turnos",
    "vacaciones",
    "curriculums",
    "correo",
    "nominas",
    "documentos",
    "trabajo_temporal",
    "analitica",
    "informes",
}


def _eval_files() -> list[Path]:
    return sorted(EVALS_DIR.glob("*.yaml"))


def _load(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, list), f"{path.name}: el YAML debe ser una lista de entradas"
    return data


def iter_eval_prompts() -> list[tuple[str, dict[str, Any]]]:
    """Todas las entradas de todos los ficheros, con el nombre de fichero de origen."""
    entries: list[tuple[str, dict[str, Any]]] = []
    for path in _eval_files():
        for entry in _load(path):
            entries.append((path.name, entry))
    return entries


def test_eval_files_exist() -> None:
    files = _eval_files()
    assert len(files) >= 13, "Se esperan al menos 13 categorías de evaluación"


@pytest.mark.parametrize("path", _eval_files(), ids=lambda p: p.name)
def test_eval_file_entries_well_formed(path: Path) -> None:
    entries = _load(path)
    assert entries, f"{path.name} no debe estar vacío"
    for i, entry in enumerate(entries):
        assert isinstance(entry, dict), f"{path.name}[{i}]: cada entrada debe ser un mapping"
        has_prompt = isinstance(entry.get("prompt"), str) and entry["prompt"].strip()
        assert has_prompt, f"{path.name}[{i}]: falta 'prompt' no vacío"

        if "previous" in entry:
            assert isinstance(entry["previous"], str) and entry["previous"].strip(), (
                f"{path.name}[{i}]: 'previous' debe ser texto no vacío cuando está presente"
            )

        domain = entry.get("domain")
        domains = domain if isinstance(domain, list) else [domain]
        for d in domains:
            assert d is None or d in KNOWN_DOMAINS, (
                f"{path.name}[{i}]: dominio desconocido {d!r} (añadir a KNOWN_DOMAINS si es nuevo)"
            )

        tags = entry.get("tags")
        assert isinstance(tags, list) and tags, f"{path.name}[{i}]: 'tags' debe ser una lista no vacía"


def test_total_prompt_count_meets_minimum() -> None:
    total = sum(len(_load(p)) for p in _eval_files())
    assert total >= MIN_TOTAL_PROMPTS, (
        f"El banco de evaluación tiene {total} prompts, por debajo del mínimo {MIN_TOTAL_PROMPTS}"
    )


def test_no_duplicate_prompts_within_file() -> None:
    for path in _eval_files():
        prompts = [e["prompt"].strip().lower() for e in _load(path)]
        dupes = {p for p in prompts if prompts.count(p) > 1}
        assert not dupes, f"{path.name}: prompts duplicados: {dupes}"
