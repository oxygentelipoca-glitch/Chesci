import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = process.env.CHEMFINDER_BACKEND_URL || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
      },
      '/auth': {
        target: backend,
        changeOrigin: true,
      },
      '/files': {
        target: backend,
        changeOrigin: true,
      },
      '/upload': {
        target: backend,
        changeOrigin: true,
      },
    },
  },
})
