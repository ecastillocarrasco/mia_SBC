"""Catálogo semántico (Bloque II, Fase B): metadatos de procedencia/granularidad/k-anonimato añadidos
sobre el registro existente, y `resolve_all()` para peticiones que mencionan varios campos a la vez.

Condición obligatoria del usuario: las reglas de k-anonimato de Nóminas no se duplican ni se debilitan
al incorporarlas al catálogo — se refleja el mismo valor (`min_group=3`) y una prueba de consistencia
aquí falla si una de las dos copias cambia sin la otra, en vez de importar directamente
`mia.modules.rrhh.nominas.estadisticas` desde `mia.query` (evitaría invertir la dirección de
dependencia: `query/` es infraestructura genérica, `nominas/` es un dominio de negocio concreto)."""

from __future__ import annotations

from mia.modules.rrhh.nominas.estadisticas import MIN_GROUP
from mia.query.fields import field_registry


def test_payroll_fields_mirror_the_real_k_anonymity_threshold() -> None:
    payroll_fields = field_registry.by_domain("payroll")
    assert payroll_fields, "el catálogo debe seguir teniendo campos de nóminas"
    for fd in payroll_fields:
        assert fd.min_group == MIN_GROUP, (
            f"{fd.name}: min_group del catálogo ({fd.min_group}) no coincide con "
            f"nominas.estadisticas.MIN_GROUP ({MIN_GROUP}) — o se actualiza el catálogo, o se "
            f"revierte el cambio en nóminas, pero nunca deben divergir en silencio"
        )
        assert fd.permission == "NOMINAS_IMPORTES"


def test_non_payroll_fields_have_no_k_anonymity_threshold() -> None:
    for fd in field_registry.all_fields():
        if fd.domain != "payroll":
            assert fd.min_group is None, f"{fd.name}: solo nóminas debe llevar min_group por ahora"


def test_every_field_declares_real_provenance() -> None:
    """Ningún campo debe quedar sin procedencia declarada (ni inventada ni vacía) — es justo la
    información que faltaba según la auditoría de la Fase A."""
    for fd in field_registry.all_fields():
        assert fd.source, f"{fd.name}: falta declarar su procedencia real (source)"
        assert fd.granularity, f"{fd.name}: falta declarar su granularidad"


def test_resolve_all_finds_every_mentioned_field_once() -> None:
    fields = field_registry.resolve_all("evolución de plantilla por departamento y puesto")
    names = [fd.name for fd in fields]
    assert "department" in names
    assert "position" in names
    assert len(names) == len(set(names))  # cada campo aparece una sola vez


def test_resolve_all_prefers_longer_synonyms_without_duplicating() -> None:
    """«salario neto» no debe colarse también como coincidencia separada de un sinónimo más corto del
    mismo campo — debe aparecer una sola vez como `liquido`."""
    fields = field_registry.resolve_all("comparativa de salario neto por departamento")
    names = [fd.name for fd in fields]
    assert names.count("liquido") == 1
    assert "department" in names


def test_resolve_all_returns_empty_for_unrelated_text() -> None:
    assert field_registry.resolve_all("hola, buenos días") == []
