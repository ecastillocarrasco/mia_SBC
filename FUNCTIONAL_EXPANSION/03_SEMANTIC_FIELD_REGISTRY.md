# 03 — Semantic Field Registry

Módulo: `src/mia/query/fields.py`. Mapea sinónimos en español (normalizados
sin tildes vía `mia.text.normalize_key`) a un campo interno (`FieldDef`), con
dominio, tipo, operaciones de agregación válidas y permiso requerido.

## Por qué existe

Antes de esta capa, el vocabulario natural que acepta cada tool vivía
disperso en la `description` de cada `Field` de Pydantic, duplicado tool a
tool. Esta capa centraliza **"cómo se dice" → "qué campo es"** en un solo
sitio consultable, para que añadir un sinónimo no implique tocar ninguna
tool.

## Ejemplo

```python
field_registry.resolve("cuánto cobra")
# FieldDef(name="liquido", domain="payroll", permission="NOMINAS_IMPORTES", unit="€", ...)

field_registry.resolve("antiguedad")
# FieldDef(name="hire_date", domain="employee", agg_ops=("min","max","distribution","trend"))

field_registry.by_domain("payroll")
# [liquido, total_devengado, irpf, coste_empresa]
```

La resolución es por substring: si el texto contiene un sinónimo conocido,
gana el sinónimo más largo que haga match (evita que "a" case con cualquier
frase). Coincidencia exacta normalizada tiene prioridad.

## Catálogo actual

9 campos de empleado (`name`, `department`, `position`, `age`, `active`,
`hire_date`, `gender`, `contract_type`, `nationality`), 4 de turnos, 2 de
vacaciones, 4 de nómina (marcados con `permission="NOMINAS_IMPORTES"`), 2 de
documentos, 2 de ETT. `gender` y `hire_date` están marcados explícitamente
como "campo no disponible actualmente en todos los empleados" —
`CLAUDE.md` prohíbe simular funcionalidad inexistente, así que el registro
documenta la limitación en el propio `FieldDef.description` en vez de
ocultarla.

## Permiso como parte del campo, no de la tool

`liquido`, `total_devengado`, `irpf`, `coste_empresa` llevan
`permission="NOMINAS_IMPORTES"` en el propio `FieldDef`. Si una futura tool
consulta el registro para decidir qué campos mostrar, el filtrado por
permiso viene gratis — no hay que recordarlo en cada sitio nuevo.

## Estado de integración y pruebas

Como el resto de `mia/query/`, construido y probado de forma aislada;
ninguna tool lo consulta todavía en su handler (ver
[02_UNIVERSAL_QUERY_ENGINE.md](02_UNIVERSAL_QUERY_ENGINE.md) para el motivo).
Pruebas en `tests/test_query_engine.py` (`test_field_registry_*`):
resolución exacta, por sinónimo acentuado/sin acentuar, ausencia de match y
filtrado por dominio.
