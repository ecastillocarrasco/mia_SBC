# Frontend de mIA

Tres mundos sobre un mismo núcleo. Todos hablan con el backend nuevo (`/api/chat/stream`,
`/api/voice/stream`) y comparten sesión: puedes empezar en 2D y seguir en 3D.

| Mundo | Ruta | Código |
|---|---|---|
| Portada | `/` | Elegir mundo |
| Universo 2D | `/mia-2d.html` | **Idéntico al anterior** (`src/worlds/2D/`) |
| Mundo 3D | `/mia-3d.html` | **Idéntico al anterior** (`src/main.js`, `src/style.css`) |
| Holograma | `/src/worlds/hologram/` | Nuevo, sobre `src/core/` |

El 2D y el 3D son una copia exacta del frontend anterior. Solo cambia un enlace: el botón
«3D» del universo 2D apuntaba a `/`, que ahora es la portada, y pasa a `/mia-3d.html`.
Llaman como antes a `127.0.0.1:5001` y `:5002`: mIA nueva atiende ambos puertos con sus
alias de compatibilidad. Los recursos `/mia-assets/*` (avatar y logo), que antes servía
el backend Flask, están ahora en `public/mia-assets/`.

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
