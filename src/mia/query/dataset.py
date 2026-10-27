"""NormalizedDataset — contrato de datos interoperable.

Todas las tools que producen conjuntos de filas pueden emitir un
NormalizedDataset además de su presentación habitual. Esto permite:

  * filtrar / ordenar / agrupar en el UniversalQueryEngine
  * exportar a Excel / PDF de forma uniforme
  * cruzar datasets de distintos dominios
  * pasar al InsightEngine para detectar hechos relevantes

El dataset no reemplaza las presentaciones especializadas (Employee360,
panel de departamento…); es una representación adicional, interoperable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

Row = dict[str, Any]
"""Una fila del dataset: claves = nombre de campo, valores = valor primitivo."""


@dataclass(frozen=True, slots=True)
class Schema:
    """Describe las columnas del dataset."""

    name: str
    """Nombre del campo (clave en cada Row)."""
    label: str
    """Etiqueta legible para mostrar al usuario."""
    type: str
    """Tipo de dato: 'string', 'int', 'float', 'date', 'bool', 'enum'."""
    unit: str | None = None
    sortable: bool = True
    aggregable: bool = True


@dataclass
class NormalizedDataset:
    """Conjunto de filas con esquema y metadatos de origen.

    Attributes:
        title:    Título descriptivo del dataset.
        schema:   Definición de columnas (orden importa para tablas).
        rows:     Lista de filas (dicts con las claves del schema).
        source:   Nombre(s) de la fuente de datos original.
        filters:  Filtros aplicados al construir el dataset (para trazabilidad).
        period:   Periodo de los datos si aplica.
        generated_at: Timestamp de generación.
        total_count:  Total de filas disponibles antes de truncar (puede ser > len(rows)).
        is_truncated: True si se aplicó un límite de filas.
        permissions:  Permisos que se han comprobado para generar este dataset.
        notes:    Notas adicionales (calidad de datos, fuente parcial…).
    """

    title: str
    schema: list[Schema]
    rows: list[Row]
    source: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    period: dict[str, str] = field(default_factory=dict)
    generated_at: datetime | None = None
    total_count: int | None = None
    is_truncated: bool = False
    permissions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers
    def column_names(self) -> list[str]:
        return [s.name for s in self.schema]

    def column_labels(self) -> list[str]:
        return [s.label for s in self.schema]

    def to_table_rows(self) -> list[list[Any]]:
        """Convierte las filas a listas alineadas con el schema (para tablas HTML / PDF)."""
        cols = self.column_names()
        return [[row.get(c) for c in cols] for row in self.rows]

    def get_column(self, name: str) -> list[Any]:
        """Todos los valores de una columna (None si falta)."""
        return [row.get(name) for row in self.rows]

    def numeric_column(self, name: str) -> list[float]:
        """Valores numéricos de una columna (ignora None y no numéricos)."""
        out = []
        for v in self.get_column(name):
            if isinstance(v, int | float) and not isinstance(v, bool):
                out.append(float(v))
        return out

    def to_presentation(self) -> dict[str, Any]:
        """Emite un objeto de presentación compatible con el frontend (tipo 'table')."""
        return {
            "type": "table",
            "title": self.title,
            "columns": self.column_labels(),
            "rows": self.to_table_rows(),
            "total": self.total_count or len(self.rows),
            "truncated": self.is_truncated,
        }

    def clone_with(self, *, rows: list[Row] | None = None, title: str | None = None) -> NormalizedDataset:
        """Crea una copia modificando solo los campos indicados."""
        return NormalizedDataset(
            title=title or self.title,
            schema=self.schema,
            rows=rows if rows is not None else list(self.rows),
            source=list(self.source),
            filters=dict(self.filters),
            period=dict(self.period),
            generated_at=self.generated_at,
            total_count=self.total_count,
            is_truncated=self.is_truncated,
            permissions=list(self.permissions),
            notes=list(self.notes),
        )

    # ------------------------------------------------------------------ factory
    @classmethod
    def from_dicts(
        cls,
        title: str,
        rows: list[dict[str, Any]],
        *,
        labels: dict[str, str] | None = None,
        source: list[str] | None = None,
        **kwargs: Any,
    ) -> NormalizedDataset:
        """Infiere el schema a partir de los dicts y etiquetas opcionales."""
        if not rows:
            return cls(title=title, schema=[], rows=[], source=source or [], **kwargs)
        all_keys: list[str] = list(dict.fromkeys(k for row in rows for k in row))
        schema = []
        for k in all_keys:
            sample = next((row[k] for row in rows if row.get(k) is not None), None)
            ftype = (
                "bool"
                if isinstance(sample, bool)
                else "int"
                if isinstance(sample, int)
                else "float"
                if isinstance(sample, float)
                else "date"
                if isinstance(sample, date)
                else "string"
            )
            schema.append(
                Schema(
                    name=k,
                    label=(labels or {}).get(k, k.replace("_", " ").title()),
                    type=ftype,
                    aggregable=ftype in ("int", "float"),
                )
            )
        return cls(title=title, schema=schema, rows=rows, source=source or [], **kwargs)
