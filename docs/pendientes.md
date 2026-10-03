# Pendientes

Hallazgos reales, investigados y con causa raíz identificada, que se aplazan a propósito
(decisión explícita del usuario, no olvido). No tocar sin confirmar primero que sigue
vigente: comprobar que los números no han cambiado desde la fecha de la nota.

---

## Tarea 4 (Fase 1 — paridad RRHH): cobertura y determinismo de búsqueda de CVs

Añadido: 03/10. Bloquea el cierre de la Fase 1 (su criterio de cierre exige
`tools/diagnostico_paridad.py`/`tools/shadow_compare.py` sin discrepancias de negocio).

### 1. Cobertura: 208 de 1.461 CV sin texto extraído

Verificado contra la base de datos real:

```
CvText por estado →  error: 208 · unsupported: 8 · ok: 1245
```

De esos 208 "error", **186 son `ModuleNotFoundError: No module named 'pypdfium2'`** (el resto:
19 `PdfStreamError`, 3 `KeyError: '/DescendantFonts'`, PDFs genuinamente dañados).

`pypdfium2` está declarado en `pyproject.toml` y SÍ es importable en este entorno de
desarrollo — el fallo ocurrió en el entorno donde corrió `CvIndexer` contra SharePoint real
(`src/mia/modules/rrhh/curriculums/indexer.py`), que no lo tenía instalado en ese momento.
No es un bug de código: es un problema de entorno/despliegue de ese servidor.

**Acción pendiente:** confirmar que `pypdfium2` está instalado en el entorno donde se ejecuta
`python -m mia.ingestion.sync` / la indexación de CVs en producción, y volver a lanzar
`CvIndexer.run()` (relee solo lo pendiente/modificado, no reprocesa los 1.245 ya indexados).
Recuperaría la mayoría de los 186 — no los 19+3 genuinamente corruptos.

Decisión del usuario (03/10): aplazado — implica descargar de SharePoint y llamar a la API de
embeddings (coste real) escribiendo en la base de datos compartida.

### 2. No-determinismo: la búsqueda semántica usa sinónimos que varían entre llamadas

`src/mia/modules/rrhh/curriculums/tools.py:361` (`_semantic_pass`):

```python
vector = (await deps.llm.embed([" ".join([r.termino, *r.equivalentes])], model))[0]
```

`r.equivalentes` lo redacta el modelo en cada llamada (parámetro `BuscarParams.requisitos`,
campo `Requisito.equivalentes` en `requirements.py`/`tools.py`). Para requisitos sin entrada en
`BUILTIN_EQUIVALENTS` (`requirements.py`, solo cubre idiomas y «cocina») — por ejemplo nombres
de empresa como «Marriott» o «Meliá» — el resultado depende enteramente de qué sinónimos se le
ocurra escribir al modelo esa llamada, porque entran directamente en el texto que se embebe.
Esto explica el no-determinismo reportado (59 vs 81 resultados en «cocina e inglés» — con
«cocina» parcialmente protegido por `BUILTIN_EQUIVALENTS`, pero «inglés» mezclando lo fijo con
lo variable) y probablemente buena parte del «2 vs 573» de «Marriott o Meliá» (sin ninguna red
de seguridad fija).

**Fix propuesto, no aplicado:** embeber solo `r.termino` (sin `r.equivalentes`) en la llamada
semántica — determinista y cacheable por construcción, y en teoría no debería empeorar la
calidad (mezclar varios sinónimos en una sola embedding diluye el vector en vez de afinarlo).
`equivalentes` seguiría usándose igual que hoy en el paso léxico (`check_lexical`/`terms_for`),
donde la coincidencia literal exacta sí aporta.

**Riesgo del fix:** cambia qué candidatos aparecen como «posible» coincidencia en búsquedas
reales. No se puede validar la calidad semántica sin una llamada real a embeddings (el
`FakeLLMProvider` de los tests usa un hash de palabras, no sirve para juzgar esto).

Decisión del usuario (03/10): aplazado — quiere validarlo con casos reales primero (p. ej.
modo sombra) antes de cambiar cómo se buscan candidatos.

### Para retomar

1. Confirmar con `tools/diagnostico_paridad.py` o una consulta directa que los números de
   arriba (208/1.461, 186 por pypdfium2) siguen vigentes.
2. Decidir primero la reindexación (sin riesgo de calidad, solo coste) y medir si por sí sola
   reduce el no-determinismo observado (más cobertura puede estabilizar qué aparece).
3. Si el no-determinismo persiste, aplicar el fix de `_semantic_pass` y comparar resultados
   antes/después sobre consultas reales del corpus de modo sombra, no solo con tests.
