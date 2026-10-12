# mIA Sunset Beach Club — Holograma V5.2.5

## Qué se ha encontrado

La traza real de V5.2.4 indicaba: `http: 200`, `events: 5`,
`lastError: inactivity`, `elapsedSeconds: 27`, `result: false`,
`requestStarted: true`, `uiWarning: thinking-animation`.

**Eso NO significa que hubiera cero trabajadores.** Significa que el
holograma recibió cinco eventos SSE pero no recibió un resultado
final reconocible antes de cancelar la consulta por 25 s de inactividad.

Comparación del frontend recibido:

- Mundo 2D: POST `/api/mia/v4/chat` (JSON, gateway LLM), luego
  `/api/mia/chat/stream` (NDJSON, `type=result` y `payload`), finalmente
  `/api/mia/chat` (JSON). Envía `{message, context}`.
- Holograma hasta V5.2.4: POST `/api/chat/stream` (SSE), envía
  `{message, session_id}` y exige `event: result` con `data.result`.
- `vite.config.js` original: `/api/mia/v4` apunta a puerto 5002;
  `/api` a puerto 5001. Por tanto, no solo cambia el formato: puede
  cambiar también el servicio que interpreta la consulta.

V5.2.5 alinea **solo el holograma** con el circuito de consultas del 2D,
pero mantiene su presentación holográfica, respuestas ejecutivas, voz,
KPI y gestos independientes.

## Archivos del parche

- `src/worlds/hologram/hologram-api-v525.js` — NUEVO adaptador JSON/NDJSON
  con las tres rutas del 2D, contexto propio de sesión y datos normalizados.
- `src/worlds/hologram/main.js` — utiliza el adaptador nuevo, mantiene
  `adaptHologramResult` y `hologramExecutiveCopy`, plazos y diagnóstico.
- `src/worlds/hologram/hologram-lifecycle-v523.js` — añade `route` al
  diagnóstico seguro y actualiza versión a 5.2.5 (nombre de archivo
  conservado por compatibilidad).
- `src/worlds/hologram/hologram-director-v52.js` — si una animación falla,
  se vuelve a reposo sin impedir consulta/resultados.
- `src/worlds/hologram/index.html` — renueva los query strings de caché y
  muestra V5.2.5 en diagnóstico.

No se modifica 3D, 2D, `src/core`, backend, GLB, rig, texturas ni otros
estilos del holograma.

## Instalación

1. Haz copia de `frontend/src/worlds/hologram/`.
2. Extrae el ZIP dentro de la raíz de `frontend/` (no directamente
   dentro de `hologram/`): conserva la estructura y sobrescribe los
   cuatro archivos indicados; copia el módulo nuevo.
3. Conserva los CSS existentes y el GLB original.
4. Reinicia `npm run dev` (o ejecuta `npm run build` y publica `dist`
   si la instalación es IIS). Recarga `Ctrl+F5`.
5. Abre `/src/worlds/hologram/index.html?diag=1` adaptando la ruta a
   tu despliegue. Para modo ventilador, `?fan=1&controls=1&diag=1`.
6. Verifica que el diagnóstico diga **HG v5.2.5**.
7. Consulta `¿Quién está trabajando ahora mismo?` y compara con 2D.

## Lectura del diagnóstico

- `route: "llm"`, `http: 200`, `result: true`: el gateway principal
  (`/api/mia/v4/chat`) devolvió una respuesta utilizable.
- `route: "backend-stream"`, `result: true`: se utilizó el respaldo
  NDJSON del 2D.
- `route: "backend-json"`, `result: true`: se utilizó el respaldo JSON.
- `route: "backend-json"`, `lastError: "upstream-unavailable"`:
  ninguno de los tres servicios entregó un resultado confirmado.
- `uiWarning: "thinking-animation"`: el error de un componente visual
  queda separado del transporte. Para el stack exacto, revisar consola F12.

No copia preguntas, nombres, identificadores de sesión ni registros de
personal en el diagnóstico. Los datos de la respuesta se mantienen como
fuente única para las cifras mostradas y narradas.

## Plazos y comportamiento

- Ruta principal LLM: hasta 120 s, como en el 2D original.
- Respaldo NDJSON: hasta 40 s sin corte adicional por inactividad de 25 s.
- Respaldo JSON: hasta 20 s.
- Límite absoluto del turno en pantalla: 185 s. Nunca una espera infinita.
- Cancelación visible tras 12 s en pantalla, o tecla Esc para el operador
  del ventilador.
- En éxito: muestra la respuesta y después reproduce voz ejecutiva.
- En error: sale de pensar, muestra un aviso y libera la entrada.

## Qué se ha probado

- 9 pruebas unitarias Node: resultado de personal y contexto correcto,
  respaldo NDJSON, respaldo JSON, JSON vacío, progreso seguido de un
  silencio de 80 ms (simulación de demora), cancelación, fracaso de todos
  los servicios, comparativas y límites de alcance.
- Chromium (mocks): solicitud por la ruta LLM, respaldo NDJSON pese a una
  excepción de animación y error terminal recuperable cuando fallan
  las tres rutas. En los tres escenarios se reactivó el botón de envío.
- Sintaxis de los JavaScript: `node --check`.

**Pendiente**: probar contra el backend real de Sunset Beach Club, su
proxy Vite/IIS y el GLB en la GPU real. No se ha realizado build completo
con el proyecto/nodemodules original ni una consulta real de trabajadores.

Si la consulta real aún falla, facilita la traza V5.2.5 sin datos
personales; `route` y `lastError` permitirán distinguir el origen.

## Reversión

Restituye los cuatro ficheros anteriores desde la copia de seguridad y
elimina `hologram-api-v525.js`. Ningún otro mundo requiere cambios.
