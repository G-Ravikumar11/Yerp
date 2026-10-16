import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { ApiError } from './api'
import { codeLine, newRef } from './errorCodes'
import { useOffline } from '@/stores/offline'
import { toast } from '@/stores/toast'
import { pageFor, useErrorPage } from '@/stores/errorPage'

interface Options<TVars, TRes> {
  /** Lists to refresh once it has worked. Prefix match: ['orders'] refreshes ['orders', 12] too. */
  invalidate?: QueryKey[]
  /** What to say. Defaults to the server's own `message`. Pass false to stay quiet. */
  success?: string | false | ((res: TRes, vars: TVars) => string)
  onSuccess?: (res: TRes, vars: TVars) => void | Promise<void>
  onError?: (err: Error, vars: TVars) => void
}

/**
 * A change sent to the server. It says what the server said - on success and
 * on failure - refreshes what the change affects, and leaves the screen to
 * decide only what to do next. Every write in the app goes through here.
 */
export function useAction<TVars = void, TRes extends object | void = { message?: string }>(
  run: (vars: TVars) => Promise<TRes>,
  { invalidate = [], success, onSuccess, onError }: Options<TVars, NonNullable<TRes>> = {},
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: async (res, vars) => {
      const refresh = Promise.all(invalidate.map((key) => qc.invalidateQueries({ queryKey: key })))
      // A refresh cannot finish without a connection; waiting on it would hold
      // the screen open on a change that was, correctly, only kept for later.
      if (useOffline.getState().online) await refresh
      const r = res as NonNullable<TRes>
      if (success !== false) {
        const text = typeof success === 'function' ? success(r, vars) : (success ?? (r as { message?: string })?.message)
        if (text) toast.success(text)
      }
      await onSuccess?.(r, vars)
    },
    onError: (err, vars) => {
      // A failure the person cannot fix by changing what they typed gets the whole error page; the screen and
      // whatever was typed stay underneath it. A mistake in the form keeps its short message.
      const page = pageFor(err)
      if (page) useErrorPage.getState().show(page)
      else toast.error(err instanceof ApiError ? err.message : failureMessage(err))
      onError?.(err, vars)
    },
  })
}

/** What to say when a call failed before the server could answer: no connection (YE-NET), or a fault here (YE-APP). */
export function failureMessage(err: unknown) {
  const offline = err instanceof TypeError || (typeof navigator !== 'undefined' && navigator.onLine === false)
  const ref = newRef()
  if (!offline) console.error(`YE-APP ref=${ref}`, err)
  return offline
    ? `Could not reach the server. Check the connection and try again. (${codeLine('YE-NET')})`
    : `Something went wrong. Try again. (${codeLine('YE-APP', ref)})`
}
