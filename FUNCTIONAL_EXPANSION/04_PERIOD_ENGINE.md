# 04 — Period Engine

Módulo: `src/mia/query/period.py`. Convierte una expresión de tiempo en
español a `ResolvedPeriod(start, end, label)` — siempre `start <= end`.
Stateless: la fecha de referencia (`today`) se pasa en cada llamada, nunca se
lee del reloj del sistema dentro del motor, así que es 100% determinista en
tests.

## Expresiones cubiertas

| Categoría | Ejemplos |
|---|---|
| Exactas | `hoy`, `ayer`, `mañana`, `esta semana`, `semana pasada`, `este mes`, `mes pasado`, `este año`, `año pasado` |
| Relativas | `últimos N días`, `últimos N meses`, `pasados N meses` |
| YTD | `ytd`, `year to date`, `desde enero`, `lo que llevamos de año` |
| Trimestre | `Q1`..`Q4` (+ año opcional), `primer/segundo/tercer/cuarto trimestre`, `trimestre actual`, `trimestre pasado` |
| Año literal | `2024`, `2025` (rechaza años fuera de 1990–año actual+1) |
| Mes nombrado | `enero`, `octubre 2025`, abreviados (`ene`, `oct`…) |
| Estación | `verano`, `otoño`, `invierno` (cruza fin de año), `primavera`, `temporada alta/baja` |
| Rango explícito | `desde X hasta Y`, `de X a Y`, `entre X y Y` — cada lado se resuelve recursivamente |

`resolve()` prueba los patrones en ese orden y devuelve el primer match;
`None` si ninguno reconoce la expresión — la tool que lo use decide si eso
es un error o si debe pedir aclaración al usuario (nunca inventa un rango).

## Por qué "entre X y Y" es recursivo

`_from_to()` separa por `hasta|a|y`, limpia prefijos (`desde`, `de`, `entre`)
y llama a `self.resolve()` en cada mitad. Así "`desde enero hasta el mes
pasado`" funciona sin código adicional: cada lado ya es una expresión
válida por sí sola.

## Límites conocidos

- Los meses con 31 días no existen en todos los años al restar meses
  (`últimos 3 meses` desde el 31 de un mes corto): cae al último día del mes
  resultante en vez de lanzar excepción (`_relative_months`).
  Es una aproximación deliberada, no un cálculo de calendario exacto.
- No resuelve fechas absolutas en formato `DD/MM/AAAA` directamente (eso lo
  cubre Pydantic cuando una tool expone un parámetro `date` explícito); este
  motor es para **lenguaje natural**, no para parsear fechas ISO.

## Estado de integración y pruebas

Construido y probado de forma aislada; ninguna tool lo invoca en su handler
todavía (ver roadmap). `tests/evals/08_temporal.yaml` enumera ~79 variantes
de lenguaje natural que un futuro cableado debería resolver; las pruebas
unitarias deterministas (fecha de referencia fija) están en
`tests/test_query_engine.py` (`test_period_engine_*`): `hoy`, relativos en
días, `mes pasado` cruzando límite de mes, trimestre con año explícito,
rango `desde...hasta`, expresión no reconocida y año literal.
