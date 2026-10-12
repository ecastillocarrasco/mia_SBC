# Mía SBC V4.6 — mirada, bienvenida natural y saludo por voz

**Aplicación:** parche incremental SOBRE V4.5. No lo instales sobre una versión anterior.
**Ámbito:** mundo 3D y saludo del holograma; núcleo de animación/voz compartido.
**Sin cambios:** mundo 2D, GLB de 84 clips, backend, texturas, rig, pesos, Employee360, tablas, micrófono de 3 estados.

## Instalar

1. Haz una copia de seguridad del frontend V4.5 completo o crea un commit de respaldo.
2. Descomprime el ZIP en la raíz de `frontend/`. Sobrescribe solo los archivos incluidos.
3. Comprueba que existe `public/models/mIA_SBC_V4_84_ANIMACIONES.glb` y que el servidor de voz `/api/voice/stream` está disponible.
4. Ejecuta `npm ci` (si aún faltan dependencias), `npm run dev`, abre el mundo 3D y recarga con `Ctrl+F5`.
5. Observa: carga -> animación y texto **¡Hola Enrique!** -> intento inmediato de voz -> regreso natural al reposo.
6. Solo tras validarlo, ejecuta `npm run build` y despliega con tu procedimiento habitual.

## Correcciones

### 1. Rostro más frontal y mirada menos alta

Se ajustan suavemente las rotaciones LOCALES de `smartrig:Neck` y `smartrig:Head` DESPUÉS de `AnimationMixer.update()`. No se mueve el modelo completo, la cadera, los pies ni las manos. Se mantienen variaciones naturales, con límite de giro. El 3D habilita la corrección; el holograma conserva la orientación original.

Los parámetros iniciales de escena en `src/worlds/3d/main.js` son:

- `pitchDeg: 6`: bajar ligeramente la mirada (en este rig +X local baja la vista).
- `yawDeg: 4`: compensar moderadamente la mirada lateral.
- `strength: 0.7`: mezcla parcial con el movimiento animado.

**Ajuste sin editar ficheros:** en `npm run dev` puedes abrir el 3D añadiendo `?facePitch=8&faceYaw=2` a su URL. Prueba incrementos pequeños, entre -10 y +12 grados. Estos parámetros de URL son exclusivos de desarrollo; no se toman de la URL en producción. Si el personaje gira hacia el lado incorrecto, invierte el signo de `faceYaw`. Evita el uso de una corrección forzada de 30–90 grados en el rig.

**Limitación:** una mirada asimétrica causada por la textura o geometría de los ojos, en lugar de los huesos de cabeza/cuello, no se puede corregir de forma precisa con estas rotaciones. En ese caso habrá que revisar el modelo en Blender, con copia de seguridad.

### 2. Fin del saludo sin gesto forzado

`mIA_SEQ_BIENVENIDA` dura 9,4 s en el GLB. Se crea una nueva acción temporal **`mIA_SEQ_BIENVENIDA_SAFE`** recortando sus ~2,2 segundos finales, que contienen el último tramo no deseado. La transición al idle empieza unos 650 ms antes del final de este clip seguro. No se borra ningún clip del GLB ni se modifica Blender.

### 3. Voz de bienvenida, sin escribir una pregunta

La voz del saludo se descarga EN PARALELO al modelo 3D; cuando aparece Mía, se intenta reproducir inmediatamente. Se reutiliza el texto del saludo personalizado por MSAL o por entorno de desarrollo. Si el navegador bloquea el `audio.play()` automático, se presenta **«Escuchar saludo»**. Al pulsarlo se reproduce el audio ya preparado SIN descargarlo de nuevo; si el servicio de voz no está disponible, se usa como respaldo la voz española del navegador.

**Limitación del navegador:** ninguna aplicación web puede garantizar audio automático con sonido cuando no existe permiso o interacción previa del usuario. No se intenta eludir esta medida. El texto y la animación sí se reproducen solos, y el control de reproducción queda visible para el usuario cuando es necesario.

El botón de micrófono para dictar sigue siendo manual (apagado -> una pregunta -> continuo -> apagado) y está SEPARADO de la voz de salida.

## Comprobaciones

- `node --test tests/mia-v46.test.mjs` : **8 correctas**.
- Compatible con `tests/mia-v45.test.mjs` (12 correctas) y `tests/mia-v44.test.mjs` (10 correctas).
- `node --check` para todos los JavaScript modificados: sin errores.

**Pendiente en tu entorno:** `npm run build` con las dependencias instaladas, WebGL sobre tu GPU, la apariencia real del rostro, la voz ElevenLabs en tu navegador y las restricciones de reproducción automática del perfil Chrome/Edge.

## Reversión

Restaura desde backup V4.5 únicamente:

- `src/core/scene.js`
- `src/core/behavior-v4.js`
- `src/core/welcome-voice-v45.js`
- `src/worlds/3d/main.js`
- `src/worlds/hologram/main.js`

No restaures el mundo 2D, ni elimines el GLB ni borres bases de datos o carpetas de Blender.
