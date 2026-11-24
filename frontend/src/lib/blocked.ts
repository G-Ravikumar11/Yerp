import { useEffect, useState } from 'react'
import { Capacitor } from '@capacitor/core'
import { ApiError } from './api'
import { serverReachable } from '@/stores/offline'

/**
 * Whether a failure that looks like "no connection" is something else, on the Android app.
 *
 * The app is another origin from the server, so when the server answers with a refusal that carries no cross-origin headers
 * (too many requests at once, a body too large, a fault before the app's own handlers) the browser hides the answer and
 * reports a bare TypeError - the same thing a dead signal gives. The whole "No connection" page was shown for it, with the
 * phone online. Asked again with a plain call to the health check, a server that answers means the connection is fine and
 * the request itself was refused.
 *
 * Only on the Android app: on the website the answer is never hidden, so a TypeError there is a real loss of connection.
 */
export async function refusedNotOffline(err: unknown): Promise<boolean> {
  if (err instanceof ApiError || !(err instanceof TypeError)) return false
  if (Capacitor.getPlatform() !== 'android') return false
  return serverReachable()
}

/** The same question for a screen that holds the failure in state. */
export function useRefusedNotOffline(err: unknown): boolean {
  const [asked, setAsked] = useState<{ err: unknown; refused: boolean } | null>(null)
  useEffect(() => {
    if (!err) return
    let live = true
    void refusedNotOffline(err).then((refused) => live && setAsked({ err, refused }))
    return () => { live = false }
  }, [err])
  return !!err && asked?.err === err && asked.refused
}

export const REFUSED_TEXT = 'The phone is online, but the server did not take that (it may be busy, or the request is too large). Nothing was saved. Wait a minute and try again.'
