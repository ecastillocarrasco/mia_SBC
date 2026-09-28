# Frontend de mIA

Tres mundos sobre un mismo núcleo. Todos hablan con el backend nuevo (`/api/chat/stream`,
`/api/voice/stream`) y comparten sesión: puedes empezar en 2D y seguir en 3D.

| Mundo | Ruta | Para qué |
|---|---|---|
| 2D | `/src/worlds/2d/` | El más rápido de probar: chat + avatar con sus 16 expresiones |
| 3D | `/src/worlds/3d/` | Escena Three.js con el modelo `mIA_WEB.glb` y sus 24 animaciones |
| Holograma | `/src/worlds/hologram/` | Proyección para pantalla o tótem: shader de borde luminoso y bandas |

## Estructura

```
frontend/
  index.html                 portada: elegir mundo
  src/core/client.js         sesión, streaming SSE y voz (sin UI)
  src/core/avatar.js         estado → imagen/etiqueta (2D y holograma)
  src/core/animations.js     estado → animación del modelo (3D y holograma)
  src/core/scene.js          escena Three.js reutilizable
  src/core/present.js        tablas, paneles, fichas y descargas (los tres mundos)
  src/worlds/{2d,3d,hologram}/
  public/assets/avatar/      las 16 expresiones
  public/models/mIA_WEB.glb  modelo 3D con animaciones
```

## Arrancar en local

Con el backend en marcha (`python -m mia`, puerto 5001), en otra consola:

```powershell
cd frontend
npm install        # solo la primera vez
npm run dev
```

Abre http://localhost:5173. Vite redirige `/api` al backend, así que no hace falta CORS.

## Qué es estructura y qué vendrá

Esta entrega deja **los tres mundos funcionando y conectados**. El pulido premium
(animaciones de entrada, ventanas modales dinámicas, coreografías al consultar, micrófono,
presentación específica por tipo de resultado…) llega en la fase de frontend premium,
después del predictivo.
