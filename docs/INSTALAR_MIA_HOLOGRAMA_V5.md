# mIA Sunset Beach Club · Holograma V5 Premium

## Alcance exacto
Parche **solo** del mundo holograma, preparado sobre los tres archivos
facilitados por el usuario: `index(6).html`, `main(6).js`, `style(6).css`.
No se modifica `src/worlds/3d`, `src/worlds/2d`, `src/core`, el backend ni
`public/models/mIA_SBC_V4_84_ANIMACIONES.glb`.

## Instalación
1. Haz copia de los archivos existentes de `frontend/src/worlds/hologram/`.
2. Extrae este ZIP en la raíz del directorio `frontend/`, respetando carpetas.
3. **Mantén tu `src/worlds/hologram/style.css` original**: no lo sustituimos;
   el nuevo estilo se añade mediante una segunda hoja CSS.
4. Comprueba que están estos 4 ficheros:
   - `src/worlds/hologram/index.html` (modificado)
   - `src/worlds/hologram/main.js` (modificado)
   - `src/worlds/hologram/hologram-premium-v5.js` (nuevo)
   - `src/worlds/hologram/hologram-premium-v5.css` (nuevo)
5. `npm run dev` en `frontend`; abre mundo holograma y recarga Ctrl+F5.

## Cambios visuales
- Rostro: ya no se aplica el ShaderMaterial aditivo translúcido que
  sustituía las texturas. Se clonan materiales y se preservan sus mapas,
  con luces del holograma, cámara más cercana y supersampling controlado.
- No se sustituye el GLB ni se alteran rig, clips o gestos.
- Se elimina el balanceo horizontal procedural impuesto por holograma.
- Narrativa cinematográfica a la izquierda con revelados y onda de voz.
- Datos a la derecha: 4 KPIs principales renderizados por el módulo
  existente `renderHologramBrief`. Barras derivadas únicamente de filas
  numéricas realmente recibidas. Anillo circular cuando un KPI es
  expresamente porcentual y se encuentra en el rango 0–100.
- Chat a la derecha, fuera del avatar central.
- Modo ventilador: añade `?fan=1` a la URL del mundo holograma. Simplifica
  la interfaz, oculta controles y mini tablas, prioriza KPIs/gráficas.
- `?quality=ultra`: presupuesto de resolución adicional, costoso en GPU.
- `?softNormals=1`: atenúa normales y bump si hay sombras anómalas;
  probarlo solo si las arrugas/manchas están causadas por ese relieve.

## Pruebas realizadas
- `node --check` para ambos JS.
- `node --test tests/mia-hologram-v5.test.mjs`: 8 pruebas aprobadas.
- CSS sin errores de parseo con tinycss2.
- Prueba DOM con Chromium: saludo, barras reales, porcentaje y limpieza.
- Revisión geométrica 1440x900 y 390x844: chat no tapa personaje en
  escritorio y no aparece scroll horizontal en móvil.

## Límites pendientes
- No se ha ejecutado build completo Vite: falta el proyecto completo con
  package.json y node_modules.
- No se ha probado el GLB real en una GPU y navegador del usuario.
- La nitidez máxima depende de la resolución de la textura facial original.
  Este parche recupera detalle que el antiguo shader ocultaba, pero no
  puede fabricar píxeles o geometría ausentes en el GLB.
- El modo ventilador es una aproximación de pantalla; el ventilador físico
  exige validar negro, brillo, distancia y tamaño de textos.

## Reversión
1. Restituye las versiones anteriores de `index.html` y `main.js`.
2. Borra `hologram-premium-v5.js` y `hologram-premium-v5.css`.
3. No es preciso revertir el GLB ni ningún módulo de otros mundos.

## Pruebas recomendadas en tu entorno
- Saludo inicial, voz y animación.
- Rostro durante IDLE, POINT y BIENVENIDA.
- 3 consultas: conversación sencilla, KPIs, comparativa entre departamentos.
- Tres pulsaciones del micrófono y desactivación.
- `?fan=1` proyectado sobre negro y `?quality=ultra` para evaluar rendimiento.
