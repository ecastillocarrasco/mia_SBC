# mIA SBC — Holograma V5.2.3: corrección verificable de espera y diagnóstico

## Qué se ha podido confirmar

La V5.2.2 no garantizaba que la interfaz abandonara el estado «pensando» ante
una conexión que no completara su respuesta. Se han corregido dos casos
concretos del código anterior:

1. Los eventos SSE `event: error` y `event: done` sin `result` se ignoraban.
   El holograma seguía mostrando animaciones de espera hasta agotar el límite.
2. Existía una rama que retornaba sin pintar un mensaje de cancelación.
   El resultado visible podía quedarse en el texto anterior de espera.
3. Los eventos de progreso tardíos podían volver a activar `thinking` mientras
   se reproducía la voz, incluso después de mostrar un resultado. Ahora el
   progreso solo se acepta durante la fase efectiva de consulta.

Ahora existe un **plazo de 55 s independiente** del transporte de red. Si llega
un resultado válido antes, se presenta normalmente. Si no llega, se muestra
claramente que **no hay datos confirmados**, sin inventar trabajadores, KPIs
ni estadísticas. Tras 12 s puedes pulsar «Cancelar espera». En el modo
ventilador limpio, la tecla `Esc` cancela una consulta.

**NO se ha confirmado la causa del fallo de la consulta real** «¿Quién está
trabajando ahora mismo?»: no tenemos acceso a su ejecución en el backend de SBC.
Esta versión permite determinar si el problema está en el SSE, la duración
del backend o la presentación del frontend.

## Instalación incremental sobre V5.2.2

1. Copia de seguridad de `frontend/src/worlds/hologram/`.
2. Extrae el ZIP en la raíz `frontend/`, conservando la estructura.
3. Se sobrescriben **solo** `src/worlds/hologram/main.js`, `index.html` y
   `hologram-projection-v52.css`.
4. Se añaden `hologram-turn-v523.js` y `hologram-lifecycle-v523.js`.
   **No borres `hologram-turn-v522.js`**. Permanece para una reversión sencilla.
5. Reinicia el servidor Vite; si sirves `dist` mediante IIS, ejecuta
   `npm run build` y publica el nuevo `dist` (copiar solo `src` no cambia un
   `dist` ya publicado).
6. Recarga sin caché (`Ctrl+F5`) y confirma la versión desde el diagnóstico.

## Diagnóstico de la consulta (necesario si sigue fallando)

1. Abre el holograma en **`?diag=1`**. Si utilizas el ventilador:
   **`?fan=1&controls=1&diag=1`**, solamente para diagnosticar.
2. Arriba a la derecha debe aparecer **`HG v5.2.3 · Diagnóstico`**. Si no,
   la versión nueva no se está sirviendo: revisar `dist`, Vite, caché e IIS.
3. Escribe exactamente **«¿Quién está trabajando ahora mismo?»**.
4. Observa si aparece respuesta, evento `error`, evento `result` o si se
   alcanza el plazo. Pulsa **«Copiar diagnóstico»** y comparte el JSON.
   Solo incluye fase, nombre del último tipo de evento, recuento, HTTP,
   segundos y error; nunca copia los nombres de empleados ni `session_id`.

Interpretación:

- `event: result`, `result: true`: llegaron datos. Si no se visualizan,
  debemos corregir el renderizador de ese formato concreto.
- `events > 0`, último `progress`, `lastError: deadline`: el backend o
  alguna herramienta sigue procesando sin emitir el `result` final.
- `event: error`, `lastError: backend-error`: el servidor notificó un fallo.
- `events: 0`, `http: null`: bloqueo antes de la respuesta HTTP, red o proxy.
- `lastError: missing-result`: el servidor cerró sin enviar respuesta final.
- Versión distinta de 5.2.3: la nueva aplicación no está publicada/cargada.

Es conveniente comparar con esa MISMA consulta en el mundo 2D, usando la misma
sesión o una conversación nueva, para distinguir el comportamiento del backend
por sesión. No copies el contenido personal del `result` al compartir capturas.

## Restricciones mantenidas

Solo cambia `src/worlds/hologram/`. No se toca el GLB, animaciones, escenas
3D/2D, módulos compartidos ni el backend. Conserva el saludo con botón,
voz, el micrófono con tres estados, y los tres materiales holográficos.

## Pruebas efectuadas

- 8 nuevas pruebas unitarias: SSE `result`, `error`, `done`, stream que ignora
  `AbortSignal`, cancelación, éxito y sanitización del diagnóstico.
- Prueba de interfaz con Chromium, módulos de escena sustituidos por stubs y
  SSE simulado: resultado, error, conexión colgada y cancelación muestran
  estado final en todos los casos sin errores JavaScript.
- `node --check` de los JS y parseo del CSS.

**No se ha validado con el backend SBC real**; las pruebas con datos sintéticos
no prueban que el backend entregue el personal correctamente. Si la captura
`?diag=1` muestra que no llega ningún resultado, hará falta revisar el backend
o el módulo de personal sin enmascarar el problema en el frontend.

## Reversión

Restituir `main.js`, `index.html` y `hologram-projection-v52.css` de la copia
V5.2.2. Puedes conservar o borrar los dos nuevos módulos `...v523.js`; ningún
otro mundo los utiliza.
