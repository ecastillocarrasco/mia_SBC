# tests/evals — Prompts de evaluación conversacional

Conjunto de ≥1000 prompts en español que cubren la cobertura funcional de mIA
SBC: cada uno representa una formulación natural que un usuario real podría
escribir, no una API call. Sirven para:

- Medir qué fracción de preguntas razonables resuelve mIA sin haber sido
  programadas literalmente (objetivo de `CLAUDE.md`: tolerancia a variación de
  lenguaje natural).
- Detectar regresiones de cobertura cuando se toca enrutado de intención,
  selección de herramienta o parsing semántico.
- Servir de banco de smoke-tests manual/semiautomático antes de un despliegue.

Estos ficheros son **datos de evaluación**, no aserciones automáticas de
comportamiento exacto: no verifican la respuesta del LLM palabra por palabra
(eso dependería del modelo en uso), sino que la pregunta se puede clasificar,
resolver con las fuentes de datos existentes y no rompe nada. La verificación
de que "se puede cargar y tiene la forma esperada" la hace
`test_evals_load.py`.

## Estructura

Cada fichero es una lista YAML de entradas. Formato de una entrada estándar:

```yaml
- prompt: "empleados del departamento de IT con contrato indefinido"
  domain: empleados          # dominio o lista de dominios ([empleados, nominas])
  tags: [filtro_múltiple, departamento, contrato]
```

Las entradas de `10_followup.yaml` añaden `previous` (la consulta del turno
anterior que fija el foco conversacional):

```yaml
- previous: "dame los datos de Ana García"
  prompt: "¿y sus vacaciones?"
  domain: vacaciones
  tags: [followup, foco_persona]
```

`domain: null` (en `14_casos_limite.yaml`) marca una pregunta fuera del
dominio de RRHH que mIA debe declinar o redirigir, no resolver.

## Categorías (14 ficheros, ~1000 prompts)

| Fichero                       | Qué cubre                                                      |
|-------------------------------|-----------------------------------------------------------------|
| `01_busqueda_basica.yaml`     | Búsqueda directa de persona/departamento/puesto, listados simples |
| `02_filtro_avanzado.yaml`     | Filtros combinados (2+ criterios: departamento+contrato, edad+jornada…) |
| `03_conteo.yaml`              | Totales y conteos simples o agrupados                           |
| `04_ranking.yaml`             | Top-N, extremos, ordenaciones                                   |
| `05_agregacion.yaml`          | Media, suma, máximo, mínimo por grupo                            |
| `06_estadistica.yaml`         | Distribuciones, percentiles, outliers, correlaciones            |
| `07_comparativa.yaml`         | A vs B, periodos, demografía, multi-grupo                       |
| `08_temporal.yaml`            | Resolución de periodos en lenguaje natural (relativo/nombrado/rango) |
| `09_multidominio.yaml`        | Cruces entre 2+ dominios (empleados+nominas+turnos…)            |
| `10_followup.yaml`            | Turnos de seguimiento que dependen del foco conversacional      |
| `11_informes.yaml`            | Generación de informes compuestos (PDF/Excel/PowerPoint)        |
| `12_visualizacion.yaml`       | Petición explícita o implícita de gráfico                       |
| `13_exportacion.yaml`         | Descarga/envío de datos o documentos en un formato              |
| `14_casos_limite.yaml`        | Ambigüedad, datos inexistentes, fuera de dominio, seguridad     |

## Uso

Cargar y validar la forma de todos los ficheros:

```bash
pytest tests/evals/test_evals_load.py -q
```

Para usarlos como banco de regresión real contra el motor conversacional
(fuera del alcance de este commit, requiere credenciales de LLM), un futuro
runner puede iterar `iter_eval_prompts()` y comprobar que cada prompt produce
una respuesta sin error y con la herramienta esperada, agregando el `%` de
cobertura por categoría — el mismo indicador que ya usa
`AUDITORIA_MIA_SBC/01_RESUMEN_EJECUTIVO.md` (226/365 preguntas, 61.9%).
