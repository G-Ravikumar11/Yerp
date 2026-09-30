import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // The existing FastAPI backend. Everything under /api is proxied so the
  // session cookie stays same-origin and no CORS setup is needed in dev.
  const api = env.VITE_API_TARGET || 'http://127.0.0.1:8931'

  return {
    // Built, the app is served by the backend under /next/; in development it owns the root.
    base: command === 'build' ? '/next/' : '/',
    build: { outDir: '../frontend-next', emptyOutDir: true },
    plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      restoreMocks: true,
    },
    server: {
      port: 5173,
      proxy: { '/api': { target: api, changeOrigin: true } },
    },
  }
})
