# mIA Sunset Beach Club V4.1 — blanco puro, voz primero y espera informativa

## Qué soluciona

1. Mundo 3D con fondo #FFFFFF uniforme (sin suelo beige, recorte de horizonte ni doble plano claro).
2. Personaje significativamente más grande y encuadrado a altura natural. El volumen depende de tres luces, sombras del modelo y sombra suave transparente debajo de los pies. No se tocan los vértices, UV, rig o texturas del GLB.
3. Los 84 clips originales permanecen disponibles. En pensamiento, escucha y habla se alternan con crossfades en lugar de pasar a IDLE a mitad de una consulta. Para KPI, ficha e informe se eligen animaciones contextualizadas; si el habla dura más que el clip, se alternan gestos explicativos.
4. La barra de consulta NO aparece inicialmente: solo se ve un pequeño botón de micrófono abajo a la derecha. Clic en el escenario o pulsación de una tecla significativa abre el campo. El botón del micrófono inicia el dictado y abre el campo. Un botón × lo oculta; también se oculta solo por inactividad cuando no hay texto ni escucha activa.
5. El dictado es el modo predeterminado. Si el permiso de micrófono ya está concedido, se intenta iniciar al entrar. Si no, el navegador necesita una interacción y/o que el usuario conceda permiso; la web no puede saltarse esa protección. El micrófono pausa la escucha durante la consulta y durante la voz de respuesta, y se rearma después.
6. Cuando el backend tarda en responder, un HUD informa tras ~7, 18, 35 y 65 segundos con mensajes HONESTOS y sin porcentajes inventados. Los mensajes SSE `progress` reales tienen prioridad durante 12 segundos. Holograma también informa mediante su leyenda.
7. Si la respuesta no contiene datos estructurados, no hay panel de resultados. Solo Mía y su comentario/voz. Cuando hay datos, permanece la capa premium de presentaciones 3D con paginación en 20 registros, fichas y gráficos ya implantados en V4.

## Requisito indispensable

Este ZIP es **acumulativo** y solo modifica archivos con respecto a `mIA_SBC_V4_PARCHE_3D_HOLOGRAMA_84.zip`. Instala primero ese parche; debe existir:

    frontend/public/models/mIA_SBC_V4_84_ANIMACIONES.glb

No se incluyen assets, mundos 2D, modelos antiguos ni `dist`.

## Instalación (solo desarrollo primero)

1. Haz backup o copia completa de los archivos `src/core/scene.js`, `src/core/behavior-v4.js`, `src/worlds/3d/index.html`, `src/worlds/3d/main.js`, `src/worlds/hologram/main.js`.
2. Detén Vite si está funcionando; descomprime el ZIP en la carpeta `frontend/`, manteniendo las rutas originales.
3. No borres `src`, `public/models` ni `dist` durante esta prueba.
4. Ejecuta en el directorio `frontend`:

    npm run dev

5. Abre `http://127.0.0.1:5173/src/worlds/3d/index.html` o la entrada del selector de mundos. Recarga con Ctrl+F5.
6. Verifica el blanco uniforme, avatar grande, micrófono visible y barra oculta al inicio.
7. En una pestaña de incógnito (sin permisos), el micro NO puede grabar silenciosamente: pulsa su botón y concede acceso. Cuando el navegador ya tenga permiso, la escucha se intentará activar automáticamente al cargar.
8. Haz consultas reales: `hola`, `¿quién está trabajando hoy?`, `compara departamentos`, `genera informe`. Revisa la diferencia entre conversación sin datos y presentación con datos.
9. Simula un backend lento o realiza una consulta larga para comprobar mensajes después de 7, 18, 35, 65 segundos. No deberían aparecer porcentajes falsos.
10. Verifica holograma y 2D antes de compilar `npm run build` y publicar a IIS.

## Pruebas locales incluidas

Desde `frontend/`, con Node.js 20+:

    node --test tests/mia-v41.test.mjs

Pruebas ejecutadas al generar: 6/6 superadas. Además se realizó un test Chromium de **interfaz con escena y backend simulados**: fondo blanco, barra inicial oculta, apertura por clic, estado de espera, respuesta sin resultados y resultados con datos, sin errores JavaScript. No sustituye prueba de WebGL, GLB, audio y backend reales.

## Cómo volver a la versión anterior

Restituye los cinco archivos respaldados y elimina exclusivamente los tres nuevos si no los necesita otro módulo:

- `src/core/voice-v4.js`
- `src/core/waiting-v4.js`
- `src/worlds/3d/v4-white.css`

También se incluye una actualización de `src/worlds/hologram/main.js` para avisos de espera; si la reviertes, conservarás el holograma anterior.

## Notas de compatibilidad

- El GLB sigue siendo el de 84 animaciones. No se importan ni modifican los FBX o archivos Blender.
- Las fichas Employee360, presentaciones estadísticas y tabla premium existentes se mantienen; este parche no reescribe sus renderizadores ni el backend.
- `src/core/scene.js` es compartido por 3D/HG: para el holograma se conserva el fondo oscuro explícito y las sombras se desactivan. Revisar visualmente en equipo real por dependencia WebGL.
- El navegador puede bloquear `SpeechRecognition` por HTTP remoto, permisos o políticas corporativas. Usa HTTPS o localhost y concede el permiso.
- **No se ha compilado todo Vite** aquí; realiza `npm run build` en tu copia antes de publicar.
