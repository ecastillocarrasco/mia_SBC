import { resolve } from "node:path";
import { defineConfig } from "vite";

// Portada (elegir mundo) + los mundos 2D y 3D anteriores tal cual + el holograma.
// Los mundos 2D y 3D llaman directamente a 127.0.0.1:5001 y :5002 (como antes); mIA nueva
// atiende ambos puertos con los alias de compatibilidad. Sus recursos /mia-assets/* ya no
// los sirve el backend: están en public/mia-assets.
export default defineConfig(({ command }) => ({
  root: __dirname,
  base: command === "build" ? "/mia/" : "/",
  server: {
    host: "127.0.0.1",
    port: 5173,
    // Igual que antes: evita los EBUSY de Windows con el GLB de mIA.
    watch: { ignored: ["**/public/models/**"] },
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
        world3d: resolve(__dirname, "mia-3d.html"),
        hologram: resolve(__dirname, "src/worlds/hologram/index.html"),
      },
    },
  },
}));
