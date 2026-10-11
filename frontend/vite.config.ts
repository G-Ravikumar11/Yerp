import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'
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
    // Built into frontend/dist, which is not committed: the deploy builds it (see nixpacks.toml).
    build: { outDir: 'dist', emptyOutDir: true },
    // Each build gets its own stamp, so data saved on the device by an older build is never trusted by a newer one.
    define: { __BUILD__: JSON.stringify(String(Date.now())) },
    plugins: [
      react(),
      tailwindcss(),
      VitePWA({
        registerType: 'prompt',
        injectRegister: false,
        includeAssets: ['favicon.svg', 'icons/apple-touch-icon.png'],
        manifest: {
          id: '/next/',
          name: 'Y ERP',
          short_name: 'Y ERP',
          description: 'The measurement book, work orders and billing for a contracting business.',
          start_url: '/next/',
          scope: '/next/',
          display: 'standalone',
          background_color: '#0b0b0e',
          theme_color: '#0b0b0e',
          categories: ['business', 'productivity'],
          icons: [
            { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
            { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
            { src: 'icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          ],
          shortcuts: [
            { name: 'Approvals', url: '/next/approvals' },
            { name: 'Measurement Book', url: '/next/subcontractors/measurement-book' },
            { name: 'RA Bills', url: '/next/subcontractors/ra-bills' },
          ],
        },
        // The app shell is kept on the device so it opens with no signal. Data is not
        // cached here: it belongs to whoever is signed in, and is kept (and cleared
        // on sign-out) by the app's own query cache.
        workbox: {
          globPatterns: ['**/*.{js,css,html,svg,png,woff2,webmanifest}'],
          navigateFallback: '/next/index.html',
          navigateFallbackDenylist: [/^\/api\//],
          maximumFileSizeToCacheInBytes: 3_000_000,
          cleanupOutdatedCaches: true,
        },
      }),
    ],
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
