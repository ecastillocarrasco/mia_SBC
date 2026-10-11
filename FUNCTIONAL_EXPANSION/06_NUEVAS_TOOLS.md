# 06 — Nuevas tools (todos los dominios)

Esta expansión no se limitó a la capa analítica universal: se añadieron
tools nuevas en **todos los dominios activos**, verificado contra
`git diff` frente al último commit (HEAD) — no solo frente al resumen de
fases A–D. Todas siguen el mismo contrato que las preexistentes: parámetros
Pydantic tipados, permiso declarado, `ToolResult` con `summary` +
`presentation` opcional, registradas vía `for factory in (...)` en el
`register()` de su módulo.

## Analítica universal (detalle en archivos separados)

Las 4 tools de `analitica/universal.py` (`analizar_departamento`,
`tendencia_metrica`, `comparar_universal`, `distribucion_plantilla`) tienen
su propio documento: [05](05_ANALYTICS_ENGINES.md) y el resto de este mismo
índice las trata en detalle de diseño; aquí solo aparecen en la tabla para
que el inventario esté completo en un único sitio.

## Inventario completo de tools nuevas

| Dominio | Tool | Responde a |
|---|---|---|
| Empleados | `perfil_edad` | Pirámide de edades de la plantilla activa (distribución por rangos, edad media, más joven/veterano), opcionalmente por departamento |
| Empleados | `cumpleanos` | Cumpleaños próximos en N días (por defecto 30), con edad que cumple |
| Empleados | `responsables` | A quién reporta una persona, el equipo de un manager, o ranking de managers por tamaño de equipo |
| Empleados | `contactos_organizacion` | Email y responsable de cada departamento/sección |
| Turnos | `horas_trabajadas` | Horas trabajadas en un periodo, por persona (desglose mes/franja) o por departamento/empresa |
| Vacaciones | `conflictos_vacaciones` | Quién del mismo departamento ya tiene vacaciones/ausencias aceptadas en un periodo concreto, con el saldo disponible de la persona — pensado para «¿puede X coger vacaciones esa semana?» |
| Nóminas | `anomalias_nominas` | Empleados sin nómina, nóminas duplicadas, nóminas huérfanas (sin empleado activo), por metadatos sin leer PDFs |
| Documentos | `cobertura_documental` | Por cada tipo de documento, cuántos de la plantilla activa lo tienen firmado y cuántos no |
| Trabajo temporal | `tarifas_tt` | Tarifas contratadas con cada ETT (precio/hora normal y nocturno, dieta, plus de contrato corto) |
| Trabajo temporal | `contactos_ett` | Datos de contacto (CIF, email, teléfono) de cada ETT |
| Trabajo temporal | `ett_hoy` | Trabajadores de ETT con boletín para hoy, con desglose por departamento y empresa |
| Trabajo temporal | `boletines_faltantes_tt` | Trabajadores ETT visibles sin boletín de horas en el periodo (por defecto, mes en curso) |
| Trabajo temporal | `variacion_coste_tt` | Compara coste, horas y boletines de ETT entre dos periodos (por defecto mes actual vs anterior) |
| Informes | `generar_informe_ejecutivo` | Informe ejecutivo completo de RRHH (KPIs, distribución, absentismo, tendencia, vacaciones, ETT) en un periodo personalizable, para dirección |
| Analítica | `analizar_departamento` | Ver [05](05_ANALYTICS_ENGINES.md) |
| Analítica | `tendencia_metrica` | Ver [05](05_ANALYTICS_ENGINES.md) |
| Analítica | `comparar_universal` | Ver [05](05_ANALYTICS_ENGINES.md) |
| Analítica | `distribucion_plantilla` | Ver [05](05_ANALYTICS_ENGINES.md) |

18 tools nuevas en total, confirmadas por inspección de cada
`register()` tras el cambio (todas aparecen en la tupla `for factory in
(...)` de su módulo, no solo definidas y olvidadas).

## Tools existentes con capacidad ampliada (no nuevas, mejoradas)

| Tool | Qué se amplió |
|---|---|
| `candidaturas` (curriculums) | El filtro de fecha ahora cae a la fecha de alta en el sistema (`created_at`) cuando no hay `applied_on`, en vez de excluir silenciosamente candidaturas sin esa fecha de SharePoint rellena |
| `buscar_candidatos` (curriculums) | También busca en comentarios, además de metadatos y CV; descripción ampliada para incluir "disponibilidad para incorporación inmediata" como requisito reconocido |
| `estadisticas_salariales` (nóminas) | Añade `suma`, percentiles 25/75 (con ≥4 nóminas leídas) y `coste_total_empresa` (devengado + aportación empresarial a la Seguridad Social, parseada por `parse_employer_ss()`, nuevo en `nominas/parser.py`) |
| `generar_informe` (informes) | El renderizado PDF (`informes/render.py`) ganó anchura de columna adaptativa (`_smart_col_widths`) para tablas con muchas columnas numéricas — mejora visual, no de contrato |

## Por qué esto no aparecía en el resumen de FASE A–D

El trabajo de estas tools se hizo en la misma sesión, en una parte anterior
a la que quedó resumida en detalle; el resumen de continuidad solo retuvo
los módulos de infraestructura nuevos (`query/`, `analytics/`,
`universal.py`, `charts.py`). Esta expansión se verificó por inspección de
`git diff` contra HEAD al cerrar la sesión, no por memoria de la
conversación — es la fuente de verdad correcta según
`CLAUDE.md` ("inspeccionar git diff antes de dar una tarea por completa").

## Dónde está probado

Ninguna de estas 18 tools tiene fixture de integración dedicada en esta
expansión (mismo motivo que las 4 universales: requieren BD poblada con
empleados/turnos/vacaciones/nóminas/ETT). Cobertura actual: arranque de
`register()` para cada dominio dentro de la suite completa
(`pytest tests/ -q`, 474 tests, ninguno falla con las 18 tools registradas).
Añadir fixtures específicas por dominio queda en
[13_ROADMAP_NEXT.md](13_ROADMAP_NEXT.md).
