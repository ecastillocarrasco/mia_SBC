import { defineConfig } from 'vite'

export default defineConfig(({ command }) => ({
  // En desarrollo trabajamos desde /
  // En producción Flask servirá la aplicación bajo /mia/
  base: command === 'build' ? '/mia/' : '/',

  server: {
    host: '127.0.0.1',
    port: 5173,

    watch: {
      // Conservamos tu configuración actual para evitar
      // los problemas de EBUSY con el GLB de mIA.
      ignored: ['**/public/models/**']
    },

    proxy: {
      /*
       * =====================================================
       * mIA LLM v4
       * =====================================================
       *
       * IMPORTANTE:
       * esta regla debe estar antes de /api porque también
       * comienza por /api.
       *
       * Frontend:
       *   /api/mia/v4/chat
       *
       * Vite:
       *   http://127.0.0.1:5002/api/mia/v4/chat
       */
      '/api/mia/v4': {
        target: 'http://127.0.0.1:5002',
        changeOrigin: true
      },

      /*
       * =====================================================
       * Backend principal mIA
       * =====================================================
       *
       * /api/mia/chat
       * /api/mia/chat/stream
       * /api/mia/v12/*
       * /api/version
       * etc.
       */
      '/api': {
        target: 'http://127.0.0.1:5001',
        changeOrigin: true
      },

      /*
       * =====================================================
       * Assets actuales del avatar 2D
       * =====================================================
       *
       * El backend legacy ya expone:
       * /mia-assets/<filename>
       */
      '/mia-assets': {
        target: 'http://127.0.0.1:5001',
        changeOrigin: true
      }
    }
  },

  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false
  }
}))