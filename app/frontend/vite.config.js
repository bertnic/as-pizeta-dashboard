import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/pizeta/dashboard/',
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // Forward full path: Flask ``application`` is mounted at ``/pizeta/dashboard`` (not at ``/``).
      '/pizeta/dashboard': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
  build: { outDir: 'dist' }
})
