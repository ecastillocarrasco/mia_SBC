# 06 - Analítica y Reporting

## Capacidades Analíticas Implementadas

### Operaciones básicas (tiempo de respuesta: <1s)

| Operación | Tool | Notas |
|---|---|---|
| COUNT | plantilla, nominas_periodo, ausencias, candidaturas | Por dominio y filtros |
| FILTRAR | operar_resultado, consulta_cruzada | Post-proceso y en origen |
| ORDENAR | operar_resultado, ranking_absentismo, ranking_salarial | Ascendente/descendente |
| AGRUPAR | plantilla(agrupar_por), consulta_cruzada(agrupar_por) | Por dept/puesto/franja_edad |
| PRIMEROS/N | operar_resultado, ranking_salarial(cuantos) | |
| SUMA | estadisticas_salariales(_stats.suma) | Solo con content_enabled+perm |
| MEDIA | estadisticas_salariales(_stats.media), perfil_edad | |
| MEDIANA | estadisticas_salariales(_stats.mediana) | Solo con content_enabled+perm |
| MIN/MAX | estadisticas_salariales(_stats.minimo/maximo) | Solo con content_enabled+perm |
| PERCENTIL 25/75 | estadisticas_salariales(_stats.percentil_25/75) | Solo con content_enabled+perm |
| CRUCE/INTERSECCIÓN | cruzar_resultados(interseccion), consulta_cruzada | |
| UNIÓN | cruzar_resultados(union) | |
| DIFERENCIA | cruzar_resultados(diferencia) | |
| TENDENCIA (MoM) | tendencia_ausencias | 3-6 meses hacia atrás |
| YoY (año anterior) | evolucion_nominas(comparar_con_anio_anterior=True) | Por persona |
| RANKING | ranking_absentismo, ranking_salarial | Con restricciones de grupo mínimo |
| PORCENTAJE | cobertura_documental, analitica_vacaciones | |
| ESTIMACIÓN | estimar_coste_tt | Solo ETT |

### Operaciones no disponibles

| Operación | Estado | Motivo |
|---|---|---|
| YoY salarial por departamento | 🟡 indirecto | Llamar estadisticas_salariales dos veces con distintos periodos |
| Correlaciones estadísticas | 🔴 | Sin módulo predictivo conectado |
| Forecasting | 🔴 | Módulo analytics/ no conectado |
| Comparativa presupuesto vs real | 🔴 | Sin datos de presupuesto |
| Análisis de productividad | 🔴 | Sin datos operativos/ventas |
| Índices compuestos (KPI personalizados) | 🟠 | Posible con consulta_cruzada pero no automático |

---

## Sistema de Informes

### Tipos disponibles

| Tipo | Formato | Herramienta | Fuente de datos | Dinámico |
|---|---|---|---|---|
| Tabla/resultado | PDF, XLSX, PPTX | `generar_informe` | LAST_TABLE de la sesión | Sí |
| Informe ejecutivo | PDF, XLSX, PPTX | `generar_informe_ejecutivo` | Múltiples dominios en tiempo real | Sí |

### Informe ejecutivo autónomo (`generar_informe_ejecutivo`)

El informe ejecutivo llama internamente a múltiples fuentes:
- Plantilla activa (por departamento)
- Ausencias del día
- Saldos de vacaciones
- Cobertura de nóminas del último mes
- Datos de ETT (TtTimesheet incluido)
- Gráficas via `rrhh/charts.py`

Genera secciones: KPIs, plantilla, ausencias, vacaciones, nóminas, ETT.

**Limitación:** No tiene parámetro de periodo explícito. Siempre usa "ahora" como referencia. Para informes históricos comparativos hay que generarlos en dos llamadas y comparar manualmente.

### Personalización

| Elemento | Configurable | Cómo |
|---|---|---|
| Logo corporativo | Sí | `MIA_REPORTS__LOGO_PATH` |
| Directorio de salida | Sí | `MIA_REPORTS__DIRECTORY` |
| TTL de ficheros | Sí | `MIA_REPORTS__TTL_HOURS` |
| Máx. filas | Sí | `MIA_REPORTS__MAX_ROWS` |
| Título | Sí | parámetro `titulo` en generar_informe |
| Colores / branding | 🔴 No | Sin parámetros de diseño en el renderer |
| Plantilla personalizada | 🔴 No | Renderer hardcoded en `informes/render.py` |

### Acceso a informes generados

Los informes se guardan en el directorio `informes/` y se sirven via `/api/reports/{id}`. El frontend muestra un botón de descarga directa.

---

## Visualizaciones en Frontend

Las visualizaciones se generan en el frontend (no en el servidor):

| Tipo | Fichero | Cuándo se muestra |
|---|---|---|
| Tabla | present.js | Resultado de cualquier tool con type=table |
| Dashboard KPIs | presentation-stage.js | Resultado de panel_rrhh |
| Gráfico de barras | presentation-charts.js | Resultados agrupados |
| Ficha 360 empleado | employee360-presentation.js | ficha_empleado con datos cruzados |
| Ficha departamento | presentation-stage.js | ficha_departamento |
| Nómina (payslip) | presentation-stage.js | nomina_importes |
| Reincorporación | presentation-stage.js | reincorporacion |
| Estadística visual | statistical-visuals.js | estadisticas_salariales |

Las visualizaciones son **dinámicas**: se generan con los datos reales devueltos por las tools en tiempo real, no son imágenes estáticas.
