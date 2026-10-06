/// <reference types="vitest" />
import { URL, fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/admin/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://127.0.0.1:8100',
    },
  },
  test: {
    globals: true,
    environment: 'node',
  },
})
