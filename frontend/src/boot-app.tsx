import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import { registerSW } from 'virtual:pwa-register'
import { Capacitor } from '@capacitor/core'
import { initMobile } from './lib/mobile'
import { toast } from './stores/toast'

void initMobile()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// The service worker keeps the app itself on the device so it opens with no signal. It never decides which version is
// shown: pages are asked of the server first (vite.config.ts), and a new build installs and takes over on its own,
// without reloading the page in front of anybody - the next page they open is simply the new build.
if (import.meta.env.PROD && !Capacitor.isNativePlatform()) {
  registerSW({
    immediate: true,
    onNeedReload() {
      // Deliberately nothing: a reload here blinked the page, and lost whatever was half typed.
    },
    onOfflineReady() {
      toast.info('Y ERP is saved on this device and opens with no signal.')
    },
    onRegisteredSW(_url, registration) {
      if (!registration) return
      // Look for a newer build when the tab is come back to, and every half hour it stays open.
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) void registration.update().catch(() => undefined)
      })
      setInterval(() => void registration.update().catch(() => undefined), 30 * 60_000)
    },
  })
}

// A tab left open across a deploy still runs the old build, whose screens are loaded the first time they are opened.
// Those files are gone from the server once the new build is out, so opening such a screen would fail. Load the new
// build instead - once: if the newest build cannot load its own files either, a reload would only repeat forever.
window.addEventListener('vite:preloadError', (event) => {
  const key = 'yerp-reloaded-for-new-build'
  let last = 0
  try { last = Number(sessionStorage.getItem(key)) || 0 } catch { /* storage blocked: reload anyway, once */ }
  if (Date.now() - last < 60_000) return
  try { sessionStorage.setItem(key, String(Date.now())) } catch { /* as above */ }
  event.preventDefault()
  window.location.reload()
})
