import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiTarget = process.env.NEXUS_API_TARGET || 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    hmr: false,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
