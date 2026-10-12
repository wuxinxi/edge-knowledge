import { resolve } from 'node:path'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env }
  return {
    root: resolve('apps/desktop'),
    plugins: [vue(), tailwindcss()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': {
          target: `http://127.0.0.1:${env.EDGE_PORT || 8765}`,
          headers: { Authorization: `Bearer ${env.EDGE_BACKEND_TOKEN || ''}` },
        },
      },
    },
  }
})
