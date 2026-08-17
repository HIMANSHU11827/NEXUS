import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // Allow a parallel/local API instance during development while
        // retaining the normal 8000 default.
        target: process.env.NEXUS_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    }
  }
})
