import { createElement, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Capacitor } from '@capacitor/core'

/* --- Keeping every open app on the newest build -------------------------------------------------------------------
   Every answer from the server says which build it is serving (X-App-Build, set by the backend's middleware). When an
   open app sees a newer one, the next change of screen loads it: the page being left is being left anyway, so nothing
   half typed is lost, and nobody has to clear anything or press reload.
   A tab or the installed app left open over a deploy went on showing the old design when it was come back to, until
   something was clicked. So coming back to it asks the server at once, and loads the new build there and then - unless
   a form or a dialog is open, when a bar offers the reload instead of taking what was being typed.                   */

declare const __BUILD__: string

// The phone app carries its own copy of the screens; a reload cannot bring it a newer one.
const watching = !Capacitor.isNativePlatform() && import.meta.env.PROD
let newer = ''
const listeners = new Set<() => void>()

/** Called with every answer the app gets from the server. */
export function noteAnswer(res: Response) {
  if (!watching) return
  const build = res.headers.get('X-App-Build')
  if (build && build !== __BUILD__ && build !== newer) {
    newer = build
    listeners.forEach((tell) => tell())
  }
  const reset = res.headers.get('X-Client-Reset')
  if (reset) void resetIfAsked(reset)
}

/** Loads the newer build. Once per build: if the page that loads is still not it (the deploy not finished), carry on
    rather than loop. */
function loadNewer() {
  const key = 'yerp-loaded-build'
  try {
    if (sessionStorage.getItem(key) === newer) return
    sessionStorage.setItem(key, newer)
  } catch { /* storage blocked: load it anyway, this once */ }
  window.location.reload()
}

/** Something the person may be in the middle of, that a reload would lose: a form, a dialog, a box being typed in. */
export function midWork() {
  return !!document.querySelector('form, [role="dialog"], textarea') || document.activeElement instanceof HTMLInputElement
}

/** Asks the server which build it serves: one small request, made when the app is come back to. */
async function askBuild() {
  try {
    const { apiUrl } = await import('./api')
    noteAnswer(await fetch(apiUrl('/api/health'), { cache: 'no-store', credentials: 'include' }))
  } catch { /* no signal: the next answer will say */ }
}

/** Loads the newer build at the next change of screen, or at once when the app is come back to. Rendered once, inside
    the router; draws the reload bar when a newer build is waiting behind something being typed. */
export function FreshBuild() {
  const { pathname } = useLocation()
  const first = useRef(true)
  const [waiting, setWaiting] = useState(false)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    if (newer) loadNewer()
  }, [pathname])
  useEffect(() => {
    if (!watching) return
    const tell = () => setWaiting(true)
    listeners.add(tell)
    const back = async () => {
      if (document.visibilityState !== 'visible') return
      await askBuild()
      if (newer && !midWork()) loadNewer()
    }
    document.addEventListener('visibilitychange', back)
    window.addEventListener('pageshow', back)
    return () => {
      listeners.delete(tell)
      document.removeEventListener('visibilitychange', back)
      window.removeEventListener('pageshow', back)
    }
  }, [])
  if (!waiting) return null
  // Drawn without JSX so this file stays plain TypeScript beside the helpers it shares.
  return createElement('div', { role: 'status', className: 'fixed inset-x-0 bottom-4 z-[90] mx-auto flex w-fit max-w-[calc(100%-2rem)] items-center gap-3 rounded-lg border border-border bg-card px-4 py-2.5 text-sm shadow-md' },
    createElement('span', null, 'A new version of Y ERP is ready.'),
    createElement('button', { type: 'button', className: 'rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground', onClick: () => window.location.reload() }, 'Reload'))
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
