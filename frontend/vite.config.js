import { resolve } from "node:path";
import { defineConfig } from "vite";

// Multipágina: la portada elige mundo; cada mundo es su propia entrada de Vite.
// En desarrollo, /api se redirige al backend de mIA (python -m mia en 127.0.0.1:5001)
// para no depender de CORS.
export default defineConfig({
  root: __dirname,
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:5001", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 800, // three.js: solo lo cargan los mundos 3D y holograma
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        world2d: resolve(__dirname, "src/worlds/2d/index.html"),
        world3d: resolve(__dirname, "src/worlds/3d/index.html"),
        hologram: resolve(__dirname, "src/worlds/hologram/index.html"),
      },
    },
  },
});
