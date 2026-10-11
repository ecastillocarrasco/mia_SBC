# 17 - Regresiones Potenciales

## Principio

Se listan las áreas donde cambios recientes o implementaciones nuevas podrían haber introducido regresiones, y donde la falta de tests específicos deja riesgo abierto.

---

## Nóminas — parser.py

### Contexto
Se implementaron recientemente `parse_concepts()` y `parse_employer_ss()`. Estos son parsers regex sobre el formato PDF del proveedor de nóminas de SBC.

### Riesgo
- Si el formato del PDF cambia (nueva versión del software de nóminas), los regex pueden fallar silenciosamente.
- Si `parse_concepts()` no encuentra la sección esperada, devuelve `{}` sin error. Esto es correcto (falla soft) pero puede no cubrir todos los formatos.
- `_EXTRA_WORD` y `_MONTHLY_NAME` en `document_kind()` usados para clasificar documentos — si los nombres cambian, la clasificación falla.
- **Test mínimo necesario:** Fixtures con PDFs de ejemplo (anonimizados) para verificar extracción de conceptos, IRPF, SS-empresa.

---

## Nóminas — estadisticas_salariales / ranking_salarial

### Contexto
Se añadieron `suma` y `percentil_25/75` a la función `_stats()` en `estadisticas.py`.

### Riesgo
- `_stats()` usa `statistics.quantiles(values, n=4)` que requiere `len(values) >= 4`. Si hay menos de 4 valores válidos, se omiten los percentiles (correcto). Pero si hay exactamente 4, los percentiles pueden ser poco representativos.
- La lógica `sample[:MAX_PEOPLE]` en `estadisticas_salariales` puede dar resultados diferentes dependiendo del orden de la query SQL (no determinista si no hay ORDER BY explícito). Esto puede afectar la suma total si el grupo es mayor de 150 personas.
- `test_salary_stats.py` fue actualizado recientemente — verificar que cubre los nuevos campos.

---

## Vacaciones — conflictos_vacaciones

### Contexto
Función nueva. Consulta vacaciones del departamento de la persona en un periodo y calcula solapamientos.

### Riesgo
- Si `e.department_key` es None, devuelve NOT_FOUND. Empleados sin departamento asignado quedan silenciosamente excluidos.
- La query filtra por `Vacation.department_key == e.department_key` — si el department_key de las vacaciones y del empleado tienen formatos inconsistentes (mayúsculas, espacios), puede no encontrar coincidencias.
- `confirmed_vacations()` aplica filtros adicionales. Si esta función cambia, puede afectar los resultados.
- Sin tests específicos detectados para esta función nueva.

---

## Analítica — proximos_jubilacion

### Contexto
Función nueva. Calcula edad y años hasta jubilación.

### Riesgo
- Usa `_EDAD_JUBILACION = 67` hardcoded. En 2027 la jubilación ordinaria en España sube a 67. Si la ley cambia y no se actualiza, los resultados pueden ser incorrectos.
- `age()` importada de `empleados/tools.py` — si ese módulo cambia la función, puede romper. Hay un `from mia.modules.rrhh.empleados.tools import age` lazy import dentro del handler.
- Sin tests específicos detectados.

---

## Trabajo Temporal — boletines_faltantes_tt y variacion_coste_tt

### Contexto
Funciones nuevas.

### Riesgo
- `boletines_faltantes_tt` cruza `TtWorker.visible` con `TtTimesheet.worker_id`. Si worker_id puede ser nulo en algunos registros, los resultados pueden ser imprecisas.
- `variacion_coste_tt` calcula diferencias de periodos dinámicamente. La lógica de "mes anterior" puede ser frágil si se ejecuta el 1 del mes a las 00:00 (borde temporal).
- Sin tests específicos detectados.

---

## Voz / Avatar

### Contexto
El módulo de voz usa `clean_speech()` del guard para eliminar importes. Los estados del avatar se generan por el LLM desde `AVATAR_GUIDE`.

### Riesgo
- Si se añaden nuevas frases con importes (no en formato español "1.234,56 €"), el regex `_MONEY` puede no capturarlas.
- El avatar state se decide por el LLM — puede ser inconsistente si el prompt cambia.
- `test_speech.py` y `test_guard.py` deben cubrir los casos de filtrado de importes en voz.

---

## Motor de Conversación — session_state

### Contexto
Las tools actualizan `session_state` con foco (persona, departamento, periodo), última tabla y última población. Esto permite referencias tipo "los de la lista anterior".

### Riesgo
- Si una tool escribe incorrectamente el estado de sesión, las referencias contextuales en turnos siguientes pueden fallar o devolver resultados de un foco anterior.
- `LAST_TABLE` y `LAST_CALL` son claves string en un dict compartido — no hay tipado fuerte.
- `test_conversation_followups.py` cubre algunos casos pero puede no cubrir todos los dominios nuevos.

---

## Consulta Cruzada

### Contexto
`consulta_cruzada` es la tool más compleja del sistema. Combina múltiples condiciones de múltiples dominios.

### Riesgo
- Nuevas condiciones añadidas a la consulta cruzada pueden interactuar con condiciones existentes de formas inesperadas.
- La condición `trabaja` filtra por ShiftDay del día actual — si el turno no está publicado, el resultado puede ser vacío aunque el empleado trabaje.
- `test_consulta_cruzada.py` es uno de los tests más grandes (13KB) — verificar que cubre las condiciones nuevas.

---

## Declaradas como "Completas" — Verificación

| Funcionalidad declarada completa | Riesgo de regresión |
|---|---|
| Employee360 / ficha_empleado | Bajo — bien testeado en test_domains.py |
| Correo (8 tools) | Bajo en código; alto si Graph API no está configurada |
| Informes ejecutivos | Medio — TtTimesheet incluido pero no siempre hay datos ETT |
| Candidatos similares (vector search) | Medio — depende de índice precargado |
| Estadísticas salariales | Bajo en código; requiere verificación con PDFs reales |
