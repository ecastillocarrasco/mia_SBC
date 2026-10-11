# mIA Sunset Beach Club V4.2.1 — Micrófono manual

**Parche correctivo encima de V4.2**. Restaura el micrófono sin cambiar las
mejoras de presentación editorial, estados de espera o animaciones.

## Instalación

1. Conserva una copia de seguridad del frontend V4.2.
2. Descomprime `mIA_SBC_V4_2_1_MICRO_MANUAL.zip` en la **raíz `frontend`**,
   respetando carpetas y sobrescribiendo únicamente las rutas incluidas.
3. `npm run dev` y `Ctrl+F5`. Valida mundo 3D y holograma.
4. Solo tras probar ejecuta `npm run build`. Nunca se modifica `dist` a mano.

## Funcionamiento

- El micrófono se muestra en ambos mundos, pero **no escucha al entrar**.
- Pulsar el botón **activa una sesión de dictado**. Si no hay permiso,
  el navegador lo pedirá solo entonces.
- Pulsarlo nuevamente **detiene la captura**.
- Al terminar de reconocer una frase, la escucha se apaga automáticamente:
  **no queda un micrófono abierto ni se rearma** por timeouts o tras la respuesta.
- El texto escrito sigue disponible sin micrófono.
- El TTS de salida de Mía sigue disponible e independiente del dictado.
- La bienvenida, el IDLE_SAFE, mensajes premium y el resumen holográfico V4.2
  se conservan.

## Pruebas

`node --test tests/mia-v42.test.mjs` — 13 pruebas automáticas superadas,
incluyendo arranque sin permiso/escucha, activación manual y finalización.
JS comprobado con `node --check` y CSS analizado sin errores de sintaxis.

**Pendiente**: ejecutar `npm run build` y probar micro/GLB/voz en tu navegador y
con tu backend reales. Esta entrega no afirma haber realizado esas pruebas.

## Rollback

Restaurar exclusivamente los archivos modificados por este ZIP desde el
respaldo V4.2. No tocar `src/worlds/2d`, el GLB de 84 animaciones ni el backend.
