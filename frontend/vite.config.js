import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { defineConfig } from "vite";

// mia-2d.js/mia-enhance.js (+ sus .css) son scripts clásicos (sin type="module"): mia-enhance.js
// depende de que las globales de mia-2d.js (window.ask, window.MIA_UI_BUILD…) ya existan en el
// ámbito global al ejecutarse, así que no se pueden convertir a módulo sin refactorizar ambos a la
// vez (ver ADVANCED_REPORTING_PROGRESS.md, sección 19). mia-2d.html los referencia con rutas
// absolutas sin type="module", y Vite por diseño nunca las procesa ni las copia a dist/ (es el
// propio aviso de "can't be bundled without type=module" en `npm run build`) — así que, sin este
// plugin, `dist/` quedaba sin ellos y el navegador recibía el HTML de index.html como fallback en su
// lugar. En `vite dev` no hace falta: el servidor de desarrollo ya sirve estos ficheros directamente
// desde `frontend/src/worlds/2d/`, sin pasar por este plugin (`apply: "build"`).
const CLASSIC_WORLD_2D_ASSETS = [
  "src/worlds/2d/mia-2d.js",
  "src/worlds/2d/mia-enhance.js",
  "src/worlds/2d/mia-2d.css",
  "src/worlds/2d/mia-enhance.css",
];

function copyClassicWorld2dAssets() {
  return {
    name: "copy-classic-world-2d-assets",
    apply: "build",
    closeBundle() {
      for (const rel of CLASSIC_WORLD_2D_ASSETS) {
        const from = resolve(__dirname, rel);
        if (!existsSync(from)) {
          throw new Error(`[copy-classic-world-2d-assets] falta el fichero fuente: ${rel}`);
        }
        const to = resolve(__dirname, "dist", rel);
        mkdirSync(dirname(to), { recursive: true });
        copyFileSync(from, to);
      }
    },
  };
}

// Portada (elegir mundo) + los mundos 2D y 3D anteriores tal cual + el holograma.
// Los mundos 2D y 3D llaman directamente a 127.0.0.1:5001 y :5002 (como antes); mIA nueva
// atiende ambos puertos con los alias de compatibilidad. Sus recursos /mia-assets/* ya no
// los sirve el backend: están en public/mia-assets.
export default defineConfig(({ command }) => ({
  root: __dirname,
  base: command === "build" ? "/mia/" : "/",
  plugins: [copyClassicWorld2dAssets()],
  // @azure/msal-browser solo se importa de forma dinámica (auth-gate.js, loadMsal()) y nunca de
  // forma estática en ningún fichero: el rastreador de dependencias de Vite puede no descubrirlo
  // a tiempo, lo que en `vite dev` provoca un primer intento de login colgado (recarga de
  // dependencias a mitad de la redirección a Microsoft). Declararlo aquí fuerza su pre-bundling.
  optimizeDeps: { include: ["@azure/msal-browser"] },
  server: {
    host: "127.0.0.1",
    port: 5173,
    // Igual que antes: evita los EBUSY de Windows con el GLB de mIA.
    watch: { ignored: ["**/public/models/**", "**/public/assets/blender/**", "**/public/assets/rigs/**", "**/public/assets/meshy/**"] },
    proxy: {
      "/api/mia/v4": { target: "http://127.0.0.1:5002", changeOrigin: true },
      "/api": { target: "http://127.0.0.1:5001", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 800, // three.js: solo lo cargan el 3D y el holograma
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        world2d: resolve(__dirname, "mia-2d.html"),
        world3d: resolve(__dirname, "src/worlds/3d/index.html"),
        world3d_legacy: resolve(__dirname, "mia-3d.html"),
        hologram: resolve(__dirname, "src/worlds/hologram/index.html"),
      },
    },
  },
}));
