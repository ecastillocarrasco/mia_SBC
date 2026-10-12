# mIA Holograma V5.2.4 — Corrección de `starting` infinito

## Punto confirmado en el código

Diagnóstico observado en la instalación del usuario:

```json
{
  "version":"5.2.3", "phase":"query", "event":"starting",
  "events":0, "http":null, "elapsedSeconds":102,
  "lastError":"-", "result":false
}
```

En V5.2.3, se lanzaba el reloj `startStatusClock()` y DESPUÉS se llamaba
fuera de `try` a `welcomeVoice.cancel()`, `hologramVoice.stop()`,
`waiting.start()`, `director.enter('thinking')` y otros componentes.
Si alguno fallaba sincrónicamente, `submit()` se rechazaba sin procesar el
error, el guard de 55 s **nunca se instalaba** y `fetch()` nunca se invocaba.

La causa específica en la instalación real (cuál de esos componentes falló)
no está demostrada sin el stack de consola. Se reprodujo el estado exacto
con un fallo de animación simulado sobre V5.2.3. La V5.2.4 pasó la misma
prueba y recibió el resultado del stream.

## Solución aplicada (solo holograma)

1. Se instala `createHologramTurnGuard` **al principio del `try`**, antes
   de iniciar o detener audio, animaciones, paneles, espera y controles.
2. Todos esos efectos de interfaz se ejecutan mediante `safely(step, fn)`:
   una excepción visual queda registrada pero no impide la consulta.
3. `finally` libera `busy` y desbloquea el envío independientemente de
   que fallen otras operaciones de limpieza.
4. El transporte registra explícitamente `requestStarted: true` justo
   antes de llamar a `fetch` (no antes).
5. El diagnóstico registra `uiWarning` con el identificador seguro del paso
   fallido; `events` cuenta únicamente eventos SSE, no fases internas.
6. Se conservan las salidas terminales de 55 s, cancelación y voz breve
   de la V5.2.3. No se inventan números de trabajadores o KPIs.

## Instalación sobre V5.2.3

1. Copia de seguridad de `frontend/src/worlds/hologram/`.
2. Extraer el ZIP en la **raíz de `frontend/`** conservando las carpetas.
3. Sobrescribir exclusivamente:
   - `src/worlds/hologram/main.js`
   - `src/worlds/hologram/index.html`
   - `src/worlds/hologram/hologram-turn-v523.js`
   - `src/worlds/hologram/hologram-lifecycle-v523.js`
4. Reiniciar `npm run dev`, o ejecutar `npm run build` y publicar `dist`
   si la web se sirve desde IIS. Recargar con Ctrl+F5.
5. No sustituir `style.css`, `hologram-projection-v52.css`, ni otros
   archivos no incluidos. No modificar el GLB.

## Prueba real importante

Abrir holograma con `?diag=1` (o `?fan=1&controls=1&diag=1`).
Confirmar que el encabezado indica **HG v5.2.4**.
Preguntar: **¿Quién está trabajando ahora mismo?**

- `requestStarted: true`, `http: 200`, `result: true`: llegó respuesta.
- `requestStarted: true`, `http: null`, `lastError: deadline`: se llamó a
  `fetch` pero el servidor/proxy no devolvió cabeceras a tiempo.
- `requestStarted: true`, `http: 200`, `events: 0`, `lastError: deadline`:
  hubo conexión HTTP, pero no llegaron eventos SSE válidos.
- `uiWarning: thinking-animation` (u otro paso): fallo de interfaz
  detectado sin bloquear el envío. Para conocer el stack, mirar consola F12.
- `phase: error`, `lastError: backend-error`: backend envió `event: error`.
- `result: false`: NO significa que hubiera cero trabajadores; indica que
  no llegó ningún resultado confirmado al frontend.

Después de 55 s como máximo se muestra un aviso recuperable (salvo bloqueo
completo del hilo JS por causas externas). Si el backend falla, NO se
mostrarán cifras ficticias. El 2D y el 3D siguen intactos.

## Pruebas efectuadas

- Chromium: reproducción sobre V5.2.3 con fallo de animación sintético
  produjo `event: starting`, `events: 0`, `http: null`, envío bloqueado.
- Chromium sobre V5.2.4: con fallos sintéticos simultáneos de bienvenida,
  espera y animación, el envío se realizó, llegó resultado SSE y volvió
  a habilitarse el control de consulta.
- Chromium V5.2.4: error SSE, fetch sin respuesta HTTP y stream sin eventos:
  los tres terminaron con una respuesta visual recuperable.
- Node: 8 pruebas unitarias específicas aprobadas.
- JavaScript: `node --check` aprobado.

No se ha ejecutado el backend real de Sunset Beach Club ni un build
completo de Vite por faltar el proyecto y sus dependencias en el entorno.

## Reversión

Restaurar los cuatro archivos anteriores de tu copia de seguridad V5.2.3.
No es necesario tocar 2D, 3D, GLB o módulos compartidos.
