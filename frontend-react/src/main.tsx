import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import { registerSW } from 'virtual:pwa-register'
import { toast } from './stores/toast'
import { useOffline } from './stores/offline'

// Arriving here ends a visit to the previous version: app.html will send the account holder back to this one.
try {
  sessionStorage.removeItem('yerp.old')
} catch {
  // Private window: nothing to clear.
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// The service worker keeps the app itself on the device, which also means a tab left open keeps
// showing the version it opened with. A new build is taken straight away when the app has only just
// opened (nothing typed, nothing to lose); later it is offered, never forced, because reloading under
// someone who is halfway through a form would lose it.
if (import.meta.env.PROD) {
  const opened = Date.now()
  const update = registerSW({
    onNeedRefresh() {
      const justOpened = Date.now() - opened < 30_000
      if (justOpened && useOffline.getState().queue.length === 0) void update(true)
      else toast.withAction('A new version of Y ERP is ready.', 'Reload', () => void update(true))
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
