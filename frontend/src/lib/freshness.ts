import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { Capacitor } from '@capacitor/core'

/* --- Keeping every open app on the newest build -------------------------------------------------------------------
   Every answer from the server says which build it is serving (X-App-Build, set by the backend's middleware). When an
   open app sees a newer one, the next change of screen loads it: the page being left is being left anyway, so nothing
   half typed is lost, and nobody has to clear anything or press reload. Costs no extra request.                      */

declare const __BUILD__: string

// The phone app carries its own copy of the screens; a reload cannot bring it a newer one.
const watching = !Capacitor.isNativePlatform() && import.meta.env.PROD
let newer = ''

/** Called with every answer the app gets from the server. */
export function noteAnswer(res: Response) {
  if (!watching) return
  const build = res.headers.get('X-App-Build')
  if (build && build !== __BUILD__) newer = build
  const reset = res.headers.get('X-Client-Reset')
  if (reset) void resetIfAsked(reset)
}

/** Loads the newer build at the next change of screen. Rendered once, inside the router. */
export function FreshBuild() {
  const { pathname } = useLocation()
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    if (!newer) return
    // Once per build: if the page that loads is still not it (the deploy not finished), carry on rather than loop.
    const key = 'yerp-loaded-build'
    try {
      if (sessionStorage.getItem(key) === newer) return
      sessionStorage.setItem(key, newer)
    } catch { /* storage blocked: load it anyway, this once */ }
    window.location.reload()
  }, [pathname])
  return null
}

/* --- Starting a device clean --------------------------------------------------------------------------------------
   For a browser holding on to something it should not: the saved copy of the app, its service worker, the data kept
   from earlier visits. Kept: the sign-in (a cookie), the theme, and any saves made offline that are still waiting to
   be sent - losing those would lose a day's site entries. /next/reset runs it, and the server's CLIENT_RESET setting
   runs it once on every device.                                                                                       */

export async function resetDevice() {
  try {
    const keys = await caches.keys()
    await Promise.all(keys.map((k) => caches.delete(k)))
  } catch { /* no Cache Storage here */ }
  try {
    const regs = (await navigator.serviceWorker?.getRegistrations()) ?? []
    await Promise.all(regs.map((r) => r.unregister()))
  } catch { /* no service worker here */ }
  try {
    // Loaded here rather than at the top: the query cache itself reads answers through the module that calls noteAnswer.
    const { forgetLocalData } = await import('./query')
    await forgetLocalData()
  } catch { /* nothing kept */ }
}

let resetting = false

async function resetIfAsked(token: string) {
  const key = 'yerp-client-reset'
  let seen: string | null = null
  try {
    seen = localStorage.getItem(key)
  } catch {
    return // nowhere to remember it: resetting on every answer would never end
  }
  if (seen === token || resetting) return
  resetting = true
  localStorage.setItem(key, token)
  // A device with no saved copy of the app has nothing old to clear: just remember the setting.
  if (!navigator.serviceWorker?.controller) return
  await resetDevice()
  window.location.reload()
}
