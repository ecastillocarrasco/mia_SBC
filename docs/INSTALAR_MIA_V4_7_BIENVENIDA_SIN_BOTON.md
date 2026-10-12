# mIA Sunset Beach Club — V4.7: saludo por voz sin botón

## Base requerida

Aplicar este ZIP **encima de mIA V4.6** (no sustituye versiones anteriores).
Descomprimir sobre la carpeta raíz del frontend respetando las rutas.
Hacer antes copia de seguridad de los archivos sobrescritos.
No contiene ni modifica GLB, Blender, 2D, backend, motor de presentación ni identidad.

## Comportamiento

1. Prepara ElevenLabs con `/api/voice/stream` durante la carga del GLB.
2. Al aparecer Mía, intenta hablar sincronizada con el saludo animado.
3. Si `Audio.play()` es bloqueado, vuelve a llamar directamente a
   `playPrepared()` en un único reintento automático; NO genera botones ni
   clics sintéticos, ni repite la petición de audio.
4. Si el segundo intento también se bloquea, el audio queda precargado y
   se reproduce durante el primer `pointerdown`, `click`, `touchstart` o
   `keydown` **real y válido** de la página, sin mostrar botón.
5. Si falla el servicio ElevenLabs, intenta voz española del navegador;
   bajo restricciones de reproducción, queda pendiente del primer gesto real.
6. Pulsar el micrófono, el botón de silenciar o enviar una pregunta no
   dispara el saludo pendiente. El dictado sigue OFF -> UNA -> CONTINUO -> OFF.
7. Al empezar una consulta, silenciar el audio o salir de página se cancelan
   los reintentos del saludo, para evitar voces tardías o duplicadas.

**Límite de los navegadores:** JavaScript no puede crear una interacción de
usuario de confianza ni forzar permisos de autoplay. Si el navegador rechaza
ambos intentos automáticos y el usuario aún no ha interactuado con la página,
no se escuchará el saludo hasta una interacción real. Esto es intencionado y
no se oculta mediante una falsa confirmación.

## Archivos incluidos

- `src/core/welcome-autostart-v47.js` — controlador nuevo de arranque de voz.
- `src/worlds/3d/main.js` y `src/worlds/hologram/main.js` — integración.
- `src/worlds/3d/index.html` y `src/worlds/hologram/index.html` — retirada del botón.
- `src/worlds/3d/v4-white.css` y `src/worlds/hologram/style.css` — limpieza de estilos obsoletos.
- `tests/mia-v45.test.mjs`, `tests/mia-v46.test.mjs`, `tests/mia-v47.test.mjs`.
- Documentación y manifiesto de hashes.

## Validación efectuada

- JS: `node --check` en los 3 ficheros JS modificados/nuevos.
- CSS: sin errores de parseo de hojas modificadas.
- Pruebas V4.5–V4.7: **29 correctas de 29**.
- Batería completa: 69 correctas de 71; las 2 restantes son aserciones V4.1
  obsoletas ya fallidas sobre el árbol original V4.6 (60/62 antes del parche),
  relativas a mensajes de espera y antiguo uso de voz del dictado.
- Build Vite: NO verificado en este entorno (`vite: not found` al carecer
  de `node_modules`). Ejecutar `npm install` si corresponde en el entorno de
  desarrollo y `npm run build` antes del despliegue.
- Autoplay real Chrome: pendiente de validar en el navegador del usuario.

## Pruebas recomendadas en tu equipo

1. `npm run dev` y recarga dura `Ctrl+F5`.
2. Abrir una pestaña nueva hacia el 3D. Deben verse el texto y la animación
   de bienvenida; la voz debe intentar arrancar sin botón.
3. Si Chrome bloquea, hacer un clic sobre una zona neutra: debe oírse la voz
   precargada sin una nueva descarga.
4. Repetir entrando al holograma.
5. Silenciar la voz y verificar que no se reactiva la bienvenida.
6. Empezar a dictar con el botón de micrófono: no debe reproducirse el saludo
   simultáneamente, y los tres estados deben permanecer disponibles.
7. Enviar una pregunta: no debe aparecer el saludo retrasado mientras responde.

## Reversión

Restaurar desde la copia previa los 6 ficheros modificados en `src/worlds/`.
El archivo nuevo `src/core/welcome-autostart-v47.js` puede quedar sin uso;
no es necesario tocar el GLB ni otra parte del proyecto.
