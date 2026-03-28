import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/pizeta/dashboard/',
  plugins: [react()],
  server: {
    proxy: {
      '/auth': 'http://localhost:8080',
      '/api':  'http://localhost:8080',
    }
  },
  build: { outDir: 'dist' }
})
