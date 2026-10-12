# mIA V4.8 — Saludo con voz al entrar en 3D, sin clic adicional

## Diagnostico

La V4.7 demostro que el audio/ElevenLabs funciona: se oye correctamente solo tras una interaccion real en la pagina 3D. La portada usa un enlace HTML (`href`) que navega a otro documento; la activacion de usuario del primer clic puede no habilitar la reproduccion automatica en el documento nuevo.

**Un clic programatico (`element.click()`) o un reintento `audio.play()` NO puede eludir las politicas del navegador.** El boton no necesita existir y no se implementa ningun clic falso.

## Que cambia

- Al seleccionar **Mundo 3D** desde `index.html`, V4.8 intercepta el clic real y monta la pagina 3D en **el mismo documento**. Evita el cambio de documento que perdiamos al navegar de la portada al 3D.
- Conserva la URL `src/worlds/3d/index.html` mediante `history.pushState` (no recarga). `main.js` se importa dinamicamente despues de cargar los estilos 3D.
- Conserva el loader premium V4.3, el modelo GLB, la voz predescargada, las animaciones y el microfono en tres estados.
- Si se falla la carga de la nueva vista, vuelve automaticamente al enlace clasico.
- Ctrl/Cmd+clic, nueva pestana y acceso directo por URL siguen usando la ruta clasica.
- Si el navegador bloquea el audio y el usuario comienza a escribir, se cancela el saludo pendiente para no interrumpirlo al abrir la barra.
- **2D y holograma no han sido modificados.**

## Instalacion

1. Guarda copia de los archivos que seran reemplazados (lista abajo).
2. Extrae el ZIP en la raiz de `frontend` encima de V4.7, respetando carpetas.
3. En la raiz `frontend`, ejecutar `npm run dev` o reconstruir el bundle con `npm run build` si se usa `dist`/IIS.
4. Entra **a traves de la portada principal** y pulsa una sola vez **Entrar en 3D**. Tras el loading, Mía deberia pronunciar «Hola Enrique» sincronizado con la animacion. Evita entrar directamente por la URL 3D al hacer esta prueba.
5. Prueba tambien `Ctrl+clic` y el boton Volver.

## Archivos sustituidos

- `index.html`
- `src/core/welcome-autostart-v47.js`
- `src/worlds/3d/main.js`

## Archivos nuevos

- `src/core/landing-world-entry-v48.js`
- `src/landing-3d-v48.js`
- `tests/mia-v48.test.mjs`
- Este documento y el manifiesto

## Validacion y limites

- 36 pruebas Node (V4.5 a V4.8) ejecutadas sin fallos. Sintaxis JS verificada.
- El navegador Chromium de este entorno bloqueo por politica administrativa incluso las paginas locales de ensayo: **no hay validacion real del audio de Chrome**.
- `node_modules` de Vite no esta disponible en este entorno, por lo que **no hemos ejecutado `npm run build`**.
- El camino normal portada -> 3D debe conservar la activacion **en navegadores que acepten reproduccion despues de una interaccion previa**. Aun asi la politica del navegador, bloqueo por usuario o contexto de sitio puede impedir autoplay.
- Si se recarga estando en `src/worlds/3d/index.html` o se accede directamente por URL, se carga la pagina 3D clasica y puede requerir una interaccion para sonar. Si se desea audio garantizado incluso en acceso directo, se necesita una pulsacion real de inicio o una configuracion de navegador administrado para kiosco/demo.

## Rollback

Restaurar `index.html`, `src/core/welcome-autostart-v47.js` y `src/worlds/3d/main.js` de la V4.7. Los dos nuevos modulos pueden quedar sin usar o eliminarse. No es necesario tocar GLB, assets, backend ni los demas mundos.
