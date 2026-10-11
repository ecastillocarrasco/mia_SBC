# 09 — Banco de evaluación conversacional (tests/evals/)

## Qué es y qué no es

`tests/evals/` contiene 1000+ prompts en español, cada uno una formulación
que un usuario real podría escribir — no una llamada a API ni una aserción
de respuesta exacta del LLM. Sirven para medir **cobertura de lenguaje
natural**, no para verificar el motor conversacional end-to-end (eso
requeriría credenciales de LLM reales y queda fuera del alcance verificable
en esta sesión).

Lo que **sí** se verifica de forma automática
(`tests/evals/test_evals_load.py`, 17 tests):

- Cada fichero YAML carga y es una lista de entradas bien formadas
  (`prompt` no vacío, `tags` no vacío, `domain` dentro del catálogo conocido
  o `null` para fuera-de-dominio).
- El total de prompts no cae por debajo de 1000 (test que falla si alguien
  borra entradas sin darse cuenta).
- No hay prompts duplicados dentro de un mismo fichero.

## 14 categorías (no 13 — se añadió una)

La especificación original pedía 13 categorías temáticas de cobertura
funcional. Se añadió una decimocuarta,
[`14_casos_limite.yaml`](../tests/evals/14_casos_limite.yaml), porque
`CLAUDE.md` exige explícitamente que la detección de intención "tolere
variación de lenguaje natural" y que mIA "no invente datos" — eso incluye
saber declinar lo que no puede responder (preguntas fuera de dominio,
predictivo no implementado, datos inexistentes, typos severos, peticiones
de seguridad a denegar). Sin esa categoría, el banco solo probaría el
camino feliz.

| # | Fichero | Prompts | Cubre |
|---|---|---|---|
| 1 | `01_busqueda_basica.yaml` | 80 | Búsqueda directa de persona/departamento/puesto |
| 2 | `02_filtro_avanzado.yaml` | 78 | 2+ criterios combinados |
| 3 | `03_conteo.yaml` | 77 | Totales y conteos agrupados |
| 4 | `04_ranking.yaml` | 76 | Top-N, extremos, ordenaciones |
| 5 | `05_agregacion.yaml` | 78 | Media, suma, máximo, mínimo |
| 6 | `06_estadistica.yaml` | 77 | Distribuciones, percentiles, outliers, correlaciones |
| 7 | `07_comparativa.yaml` | 74 | A vs B, periodos, multi-grupo |
| 8 | `08_temporal.yaml` | 79 | Periodos en lenguaje natural |
| 9 | `09_multidominio.yaml` | 68 | Cruces entre 2+ dominios |
| 10 | `10_followup.yaml` | 62 | Turnos que dependen del foco conversacional (`previous` + `prompt`) |
| 11 | `11_informes.yaml` | 64 | Generación de informes compuestos |
| 12 | `12_visualizacion.yaml` | 64 | Petición de gráfico explícita o implícita |
| 13 | `13_exportacion.yaml` | 57 | Descarga/envío en un formato concreto |
| 14 | `14_casos_limite.yaml` | 66 | Ambigüedad, fuera de dominio, datos inexistentes, seguridad |

Total: 1000 exactos a la fecha de este commit (verificado por test, no por
conteo manual — ver `test_total_prompt_count_meets_minimum`; el test exige
`>= 1000` para que añadir o quitar prompts en el futuro no rompa el umbral
sin darse cuenta).

## Por qué YAML y no un test parametrizado por prompt

Un test por prompt (1000+ tests) ejecutando el LLM real sería lento, caro y
no determinista (dependería del proveedor). El banco es **datos**,
versionables y legibles por una persona sin ejecutar nada; un futuro runner
de regresión (fuera de este commit) puede iterarlos contra un entorno con
credenciales y producir un % de cobertura por categoría, el mismo indicador
que ya usa `AUDITORIA_MIA_SBC/01_RESUMEN_EJECUTIVO.md`.

## Ejecutar

```bash
pytest tests/evals/ -q
```
