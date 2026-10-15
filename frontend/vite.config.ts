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

  const isMobile = mode === 'mobile' || env.VITE_MOBILE === 'true'
  const build = String(Date.now())

  return {
    // Built for web, the app is served by the backend under /next/; in development it owns the root.
    // Built for mobile, the app is the root of the native webview's own server (https://localhost/), so '/' - a
    // relative base would break as soon as a nested screen like /projects/diary is reloaded.
    base: isMobile ? '/' : command === 'build' ? '/next/' : '/',
    // Built into frontend/dist, which is not committed: the deploy builds it (see nixpacks.toml).
    build: { outDir: 'dist', emptyOutDir: true },
    // Each build gets its own stamp, so data saved on the device by an older build is never trusted by a newer one.
    // The same stamp is written to dist/build.json: the server puts it on every answer, and an open app that sees a
    // newer one loads it (src/lib/freshness.ts).
    define: {
      __BUILD__: JSON.stringify(build),
      // The phone app's own layout (src/app-mobile) is in the mobile build and the dev server only: for the website's build
      // this is false, so that folder is not in it at all and nothing done there can change the website.
      __MOBILE_UI__: JSON.stringify(isMobile || command === 'serve'),
    },
    plugins: [
      {
        name: 'yerp-build-stamp',
        apply: 'build',
        generateBundle() {
          this.emitFile({ type: 'asset', fileName: 'build.json', source: JSON.stringify({ build }) })
        },
      },
      react(),
      tailwindcss(),
      VitePWA({
        // A new build takes over as soon as it is installed. The page in front of the person is not reloaded under
        // them (boot-app.tsx); the next page they open is simply the new one.
        registerType: 'autoUpdate',
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
          // Opening a page asks the server first, always: answering it from the saved copy showed the build before the
          // last deploy until the page reloaded itself. The saved app shell is the answer only when the server cannot be
          // reached. The page itself is a couple of kilobytes; the scripts it names still come from the saved copy.
          navigateFallback: null,
          runtimeCaching: [
            {
              urlPattern: ({ request, url }) => request.mode === 'navigate' && url.pathname.startsWith('/next'),
              handler: 'NetworkOnly',
              options: { precacheFallback: { fallbackURL: '/next/index.html' } },
            },
          ],
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
