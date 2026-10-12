# mIA Sunset Beach Club — Holograma V5.2.1 (corrección resultados)

## Causa confirmada en el código V5.2

`hasPresentationData()` detectaba correctamente tablas, charts y otras presentaciones,
pero el holograma llamaba a `renderHologramBrief()`, que solo cubre algunos formatos.
Al recibir una tabla con filas objeto, un chart, una lista o una estructura no
admitida, podía devolver HTML vacío. `premiumStage.dataVisible()` entonces
ocultaba el panel. En `?fan=1` además se ocultan tablas y textos largos,
por lo que el resultado podía parecer completamente ausente.

Asimismo, un error posterior durante `client.speak()` podía activar el `catch`
general de la consulta y borrar una respuesta que ya se había representado.

## Qué se corrige

1. Añadido `hologram-results-v521.js`: convierte datos estructurados reales
   del backend en KPIs, tablas resumidas y comparativas, sin fabricar cifras.
   Admite filas objeto, arrays, `dashboard.kpis`, `cards`, métricas, charts,
   documentos y tablas Markdown recibidas dentro de la respuesta.
2. Se conserva `renderHologramBrief()` como respaldo ante formatos previos.
3. Cuando un formato no permite un gráfico, se muestra «Resultado disponible»
   en el ventilador, en lugar de ocultar el resultado.
4. En `?fan=1` los listados nominativos NO se proyectan: se muestra solo el
   número de filas realmente recibidas. Las gráficas se permiten únicamente
   para estructuras comparativas y tablas agregadas claramente identificadas.
5. Fallos de TTS no eliminan las tarjetas ni los mensajes mostrados.
6. No se modifican el diálogo, el cliente compartido, el micrófono, las
   animaciones exclusivas V5.2, el GLB ni los mundos 3D/2D.

## Instalación (incremental sobre V5.2)

1. Copia de seguridad de `frontend/src/worlds/hologram/`.
2. Descomprime el ZIP en la raíz de `frontend`, conservando rutas.
3. Se actualizan los archivos:
   - `src/worlds/hologram/main.js`
   - `src/worlds/hologram/index.html` (invalida caché de JS y CSS)
   - `src/worlds/hologram/hologram-projection-v52.css`
4. Archivo nuevo:
   - `src/worlds/hologram/hologram-results-v521.js`
5. No toques `src/worlds/hologram/style.css`, `src/core`, `src/worlds/3d`,
   `src/worlds/2d`, ni `public/models`.
6. Reinicia Vite/servidor y fuerza recarga (`Ctrl + F5`). Los nombres del
   CSS y JS existentes no han cambiado; si hay caché agresiva en IIS,
   invalídala o actualiza la query `?v` del HTML holograma.

## Pruebas funcionales recomendadas

- Holograma normal: preguntar «¿Quién está trabajando ahora mismo?». Las
  tablas con empleados deben dar al menos una síntesis de filas y detalles
  compatibles, en vez de un panel vacío.
- `?fan=1&controls=1`: repetir la consulta. Debe verse un indicador de
  «Registros recibidos», nunca nombres individuales de trabajadores.
- Comparar departamentos con números: debe verse la gráfica si los datos
  son agregados y numéricos; sin valores no se dibujan barras ficticias.
- Consultar un KPI: se presentan uno o dos KPIs grandes.
- Generar informe: la salida del ventilador muestra «Resultado disponible».
- Una conversación simple («Hola Mía») permanece narrativa, sin panel de
  KPIs inventado.

## Qué se ha validado

- `node --check` sobre los 3 JS implicados (nuevo adapter, main, stage base).
- 40/40 tests acumulados V5 / V5.1 / V5.2 / V5.2.1.
- CSS interpretado sin errores.
- Chromium headless (datos sintéticos): 8 escenarios monitor y ventilador,
  incluido fondo #000, tablas, charts, KPIs, documentos, panel visible y
  ausencia de scroll horizontal.
- Tests con nombres ficticios verifican que el ventilador NO muestra
  información nominativa de listados individuales.

### Pendiente

La compilación completa de Vite y la prueba contra el backend real no se
han realizado porque aquí no están desplegados sus servicios ni todas sus
dependencias. Si un resultado concreto sigue sin verse, facilitar el objeto
`result` del stream `/api/chat/stream` **anonimizado** para incorporar su
esquema a este adaptador, sin tocar los mundos 2D/3D.

## Reversión

Restaurar `main.js`, `index.html` y `hologram-projection-v52.css` previos y retirar
`hologram-results-v521.js`. No es preciso cambiar el GLB.
