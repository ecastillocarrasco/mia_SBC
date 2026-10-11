# 11 — Contratos protegidos: qué se preservó intacto

`CLAUDE.md` exige preservar toda la funcionalidad existente y no duplicar
rutas ni lógica de negocio. Esta expansión tocó más ficheros de los que el
resumen de fases A–D recogía (ver [06_NUEVAS_TOOLS.md](06_NUEVAS_TOOLS.md)
para el inventario completo, reconstruido por `git diff` contra HEAD, no
por memoria de la conversación). Verificado contra ese diff: todos los
cambios en tools preexistentes son **aditivos** — ninguna tool cambió de
nombre, de firma de parámetros obligatorios o de permiso, y ninguna
capacidad que ya funcionaba se quitó o se comportó de forma distinta.

## Qué no se tocó

- **Tools especializadas de `analitica/`** (`panel_rrhh`,
  `comparar_departamentos`, `cobertura`, `analitica_vacaciones`,
  `tendencia_ausencias`, `ranking_absentismo`, `altas`, `calidad`,
  `proximos_jubilacion`, `datos_de_personas`, `consulta_cruzada`,
  `ficha_departamento`): mismo nombre, misma firma de parámetros, mismo
  permiso, mismo `ToolResult`. `analitica/tools.py` solo ganó una línea en
  `register()` para añadir las 4 tools universales nuevas.
- **Tools de empleados/turnos/vacaciones/nóminas/documentos/trabajo_temporal
  ya existentes antes de esta sesión** (`buscar_empleado`, `ficha_empleado`,
  `plantilla`, `estructura_departamentos`, `turnos_persona`, `turnos_dia`,
  `ausencias`, `reincorporaciones`, `vacaciones`, `saldo_vacaciones`,
  `reincorporacion`, `nominas_persona`, `nominas_periodo`, `nomina_importes`,
  `evolucion_nominas`, `documentos_persona`, `documentos_faltantes`,
  `maestros_documentales`, `leer_documento`, `trabajadores_tt`,
  `boletines_tt`, `estimar_coste_tt`, `anomalias_tt`, `comunicaciones_tt`,
  `generar_informe`): mismo nombre, misma firma, mismo permiso. Lo que
  cambió en sus ficheros fue la tupla `for factory in (...)` de `register()`
  (se añadieron las tools nuevas del mismo módulo a la lista) y, en 4 casos
  puntuales, una mejora aditiva documentada abajo.

## Mejoras aditivas en tools ya existentes (no rupturas)

Verificado línea por línea en el diff: cada cambio añade capacidad o
corrige un `description` para el LLM, nunca quita un campo de salida ni
cambia el tipo de un parámetro de entrada.

- `candidaturas`: el filtro de fecha ahora también acepta `created_at` como
  respaldo cuando `applied_on` está vacío (antes excluía silenciosamente
  esas candidaturas del filtro).
- `buscar_candidatos`: también busca en comentarios, no solo metadatos+CV.
- `estadisticas_salariales`: añade `suma`, percentiles 25/75 y
  `coste_total_empresa`; los campos que ya devolvía (`media`, `mediana`,
  `minimo`, `maximo`, líquido/devengado) siguen presentes igual que antes.
- `generar_informe` (vía `informes/render.py`): anchura de columna
  adaptativa en el PDF — cambio visual, el contrato de entrada/salida de la
  tool no cambia.

## Qué más no se tocó

- **Employee360 y demás presentaciones estructuradas**: `NormalizedDataset`
  es una representación *adicional*, no un reemplazo — ver
  [02_UNIVERSAL_QUERY_ENGINE.md](02_UNIVERSAL_QUERY_ENGINE.md). Ninguna tool
  dejó de emitir su `presentation` original.
- **`chart_spec(title, columns, rows)`**: misma firma, mismo resultado para
  tablas de 2 columnas (ver [07_VISUALIZACION.md](07_VISUALIZACION.md) y
  `tests/test_charts.py::test_chart_spec_*`).
- **Reglas de negocio documentadas en `arquitectura.md`** (TUR-001/002,
  AUS-001, POB-001, VAC-001/002, DAT-001, COR-001): no se reimplementó
  ninguna; las tools nuevas que necesitan ausencias reutilizan
  `absence_periods()` ya existente, que ya las respeta.
- **Contrato de permisos**: cada tool nueva declara su `Permission` exacto
  del enum ya existente (`EMPLEADOS_LEER`, `TURNOS_LEER`); no se añadió
  ningún permiso nuevo ni se relajó ninguno existente.
- **Legacy**: ningún módulo nuevo importa de Legacy ni lo referencia. Se
  inspeccionó la auditoría (`AUDITORIA_MIA_SBC/`) solo como lectura de
  contexto, nunca como dependencia.

## Cómo se verificó

Los 362 tests preexistentes pasan sin ninguna modificación a sus
aserciones (`pytest tests/ -q`, verificado varias veces durante la sesión
a medida que se añadía código, hasta un total final de 474 tests: los 362
originales + 112 nuevos de esta expansión). Si algún contrato protegido se
hubiera alterado, el fallo habría aparecido ahí — esta expansión no
reescribió ni relajó ningún test existente para hacerlo pasar.

## Única corrección fuera del plan

`src/mia/analytics/__init__.py` quedó, de un edit anterior dentro de esta
misma sesión (previo al corte de contexto que resumió la conversación), con
texto de docstring huérfano fuera de cualquier cadena que provocaba
`SyntaxError: from __future__ imports must occur at the beginning of the
file` en cuanto cualquier módulo nuevo importaba `mia.analytics` — lo que
habría roto el arranque completo de la aplicación. Se corrigió
reestructurando el fichero (docstring de módulo + imports activos +
comentario explicativo del módulo predictivo, sin
`from __future__ import annotations` porque el proyecto corre en Python 3.12
y no lo necesita en este fichero). Es la corrección de un defecto
bloqueante propio de esta expansión, detectado al ejecutar la suite por
primera vez tras retomar la sesión — no un cambio de comportamiento de
ningún contrato preexistente.
