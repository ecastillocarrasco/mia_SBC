# 07 - Sistema de Presentación

## Arquitectura del Presentation Director

El frontend tiene un sistema de presentación completamente separado del texto de respuesta del LLM. El flujo es:

```
ToolResult.presentation → SSE result_event → client.js → presentation-director.js → presentation-stage.js
```

El LLM nunca reescribe ni interpreta el objeto `presentation`. El director JS enruta por el campo `type`.

---

## Tipos de Presentation Registrados (desde código backend)

| type | Quién lo genera | Descripción |
|---|---|---|
| `table` | Casi todas las tools | Tabla con título, columnas y filas. Mayoritariamente usado. |
| `dashboard` | `panel_rrhh` | Panel KPI con métricas numéricas y listas |
| `payslip` | `nomina_importes`, `evolucion_nominas` | Nómina individual con importes |
| `employee360` / ficha empleado | `ficha_empleado` | Ficha completa del empleado |
| `reincorporation` | `reincorporacion` | Fecha y estado de reincorporación |
| Objeto sin tipo explícito | Varias tools | Datos crudos que el director maneja genéricamente |

Además hay tipos de presentación en tools de correo y candidaturas (documentos adjuntos con botón de descarga).

---

## Componentes Frontend

| Fichero | Responsabilidad |
|---|---|
| `core/presentation-director.js` | Enruta por `type`, instancia el componente correcto |
| `core/presentation-stage.js` | Renderiza tablas, dashboards, fichas, etc. |
| `core/presentation-charts.js` | Gráficos de barras y distribuciones |
| `core/employee360-presentation.js` | Ficha 360 del empleado con datos cruzados |
| `core/statistical-visuals.js` | Visualizaciones estadísticas (percentiles, distribuciones) |
| `core/present.js` | Lógica general de presentación, scroll, eventos |
| `core/present.css` | Estilos de los componentes de presentación |
| `core/avatar-controller.js` | Controla estados del avatar según `avatar_event` |
| `core/animations.js` | Transiciones y animaciones |

---

## Cards / Objetos de Presentación Disponibles

### `table` (mayoritario)
- Campos: `title`, `columns[]`, `rows[][]`
- Se muestra como tabla HTML con ordenación visual
- Los documentos con enlace `/api/documents/...` se convierten en botones de descarga

### `dashboard`
- Campos: `title`, `kpis{}` (métricas clave), listas de ausencias y reincorporaciones
- Muestra tiles de KPIs con valores numéricos
- Incluye sección de trabajo temporal cuando es panel global

### `payslip`
- Campos: `persona`, `nominas[]` con importes por periodo
- Muestra desglose: devengado, deducciones, líquido, IRPF
- También muestra conceptos salariales si el parser los extrajo

### Ficha empleado (employee360)
- Campos: datos del empleado, departamento, puesto, manager, turnos recientes
- Componente dedicado `employee360-presentation.js`

### `reincorporation`
- Campos: persona, fecha de vuelta, tipo de ausencia
- Presentación compacta tipo tarjeta

---

## Cómo se Decide Qué Mostrar

1. Cada `Tool` retorna un `ToolResult` con campo `presentation: dict | None`
2. El motor de conversación acumula las presentaciones de todas las tools ejecutadas en el turno
3. Se emite como `result_event` por SSE
4. El Presentation Director en el frontend recibe el objeto y enruta por `type`
5. Si no hay `presentation`, el frontend solo muestra el texto de respuesta

---

## Visualizaciones que Existen y se Usan Realmente

| Visualización | Implementada | Conectada a tool real | Se activa con |
|---|---|---|---|
| Tabla de datos | Sí | Sí — todas las tools | Cualquier consulta que devuelve lista |
| Panel KPI (dashboard) | Sí | Sí — panel_rrhh | "dame el panel de RRHH", "¿cómo está la empresa?" |
| Ficha empleado 360 | Sí | Sí — ficha_empleado | "dame la ficha de X" |
| Ficha departamento | Sí | Sí — ficha_departamento | "¿cómo está el departamento de Y?" |
| Gráfico de barras | Sí | Sí — datos agrupados | plantilla/analitica por departamento |
| Payslip/nómina | Sí | Sí — nomina_importes | "¿cuánto cobró X?" (con permisos) |
| Estadísticas visuales | Sí | Sí — estadisticas_salariales | consultas salariales agregadas |
| Reincorporación card | Sí | Sí — reincorporacion | "¿cuándo vuelve X?" |
| Botones de descarga documento | Sí | Sí — documentos_persona, nominas_persona | listado de documentos |
| Botones descarga informe | Sí | Sí — generar_informe | "exporta a PDF/Excel" |

---

## Puntos de Mejora del Sistema de Presentación

1. No hay tipo `chart` dedicado para datos históricos de tendencia (tendencia_ausencias devuelve tabla).
2. El `dashboard` no tiene gráficos de tendencia (solo valores puntuales).
3. Las tablas no son editables/filtrables por el usuario directamente desde el frontend.
4. No hay tipo `calendar` para visualizar turnos de una semana.
5. No hay tipo `gantt` para visualizar periodos de vacaciones solapados.
6. El `hologram world` es un skeleton sin lógica de presentación específica.
