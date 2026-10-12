import { resolve } from 'node:path'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: resolve('apps/desktop/electron/main.ts'),
        output: { entryFileNames: 'index.js' },
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: resolve('apps/desktop/electron/preload.ts'),
        output: { format: 'cjs', entryFileNames: 'index.cjs' },
      },
    },
  },
  renderer: {
    root: resolve('apps/desktop'),
    plugins: [vue(), tailwindcss()],
    build: { rollupOptions: { input: resolve('apps/desktop/index.html') } },
  },
})
