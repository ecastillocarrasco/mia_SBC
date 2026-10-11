# 10 — Cobertura funcional: antes/después

## Punto de partida

`AUDITORIA_MIA_SBC/01_RESUMEN_EJECUTIVO.md`: 77 tools, 10 dominios activos,
226/365 preguntas de referencia cubiertas (61.9%).
`AUDITORIA_MIA_SBC/13_GAPS_FUNCIONALES.md` detallaba los huecos por dominio;
`14_OPORTUNIDADES.md` priorizaba quick wins vs inversión estratégica.

## Qué añade esta expansión a esa cifra

Esta expansión no vuelve a auditar las 365 preguntas originales (ese
ejercicio pertenece a `AUDITORIA_MIA_SBC/`, que sigue siendo la fuente de
verdad del baseline, y cuyos ficheros son parte del mismo directorio de
trabajo sin commitear — no se puede fechar con precisión milimétrica frente
a cada tool nueva de esta sesión). Lo que aporta son **18 tools nuevas**
(inventario completo en [06_NUEVAS_TOOLS.md](06_NUEVAS_TOOLS.md)) repartidas
por todos los dominios, no solo 4: generalizan sobre ejes que antes
requerían una pregunta programada literalmente. Las 4 de la capa analítica
universal son las que generalizan de forma más amplia (cualquier
departamento × cualquier métrica × cualquier periodo):

- Cualquier combinación "departamento + periodo arbitrario" para ausencias,
  bajas, vacaciones, permisos, plantilla u horas/importe ETT
  (`tendencia_metrica`, `comparar_universal`) — antes cada combinación nueva
  era, en el mejor caso, una variación de una tool existente sin soporte de
  periodo libre.
- Análisis integral de un departamento en una sola llamada
  (`analizar_departamento`) en vez de encadenar 3–4 tools especializadas.
- Distribución de plantilla por cualquier dimensión disponible
  (`distribucion_plantilla`), incluida franja de edad, que no tenía tool
  propia.

## Qué gap de la auditoría NO se cierra aquí

`13_GAPS_FUNCIONALES.md` señalaba como huecos estructurales — no de
cobertura de preguntas sino de **datos inexistentes**: finanzas (sin fuente
sincronizada), fichajes (sin fuente), evaluación de desempeño, formación.
Ninguno se implementó: `CLAUDE.md` prohíbe explícitamente inventar fuentes
de datos o simular funcionalidad inexistente. Siguen siendo huecos reales,
documentados en [12_LIMITACIONES_Y_RIESGOS.md](12_LIMITACIONES_Y_RIESGOS.md).

## Cómo medir el impacto real

El % de cobertura de la auditoría original se midió contra un banco fijo de
365 preguntas con un evaluador humano o un runner con credenciales de LLM;
esta sesión no tiene acceso a esos medios. Lo verificable aquí es
estructural: las 18 tools nuevas están registradas (ver
[06_NUEVAS_TOOLS.md](06_NUEVAS_TOOLS.md) para la verificación por módulo),
la suite completa pasa con ellas presentes
(362 tests preexistentes + 112 nuevos de esta expansión: 17 del banco de
evaluación, 63 de `mia/query/` + `mia/analytics/` y 32 de `charts.py` — ver
[12_LIMITACIONES_Y_RIESGOS.md](12_LIMITACIONES_Y_RIESGOS.md)), y el banco de
1000 prompts en `tests/evals/` queda listo para que un futuro runner con
credenciales calcule el % real por categoría — el mismo indicador que usa
`01_RESUMEN_EJECUTIVO.md`, pero repetible.
