import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import { registerSW } from 'virtual:pwa-register'
import { toast } from './stores/toast'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// The service worker keeps the app itself on the device. A new build is offered, not forced:
// reloading under someone who is halfway through a form would lose it.
if (import.meta.env.PROD) {
  const update = registerSW({
    onNeedRefresh() {
      toast.withAction('A new version of Y ERP is ready.', 'Reload', () => void update(true))
    },
    onOfflineReady() {
      toast.info('Y ERP is saved on this device and opens with no signal.')
    },
  })
}
