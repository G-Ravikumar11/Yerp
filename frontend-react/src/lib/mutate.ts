import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { ApiError } from './api'
import { toast } from '@/stores/toast'

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
      await Promise.all(invalidate.map((key) => qc.invalidateQueries({ queryKey: key })))
      const r = res as NonNullable<TRes>
      if (success !== false) {
        const text = typeof success === 'function' ? success(r, vars) : (success ?? (r as { message?: string })?.message)
        if (text) toast.success(text)
      }
      await onSuccess?.(r, vars)
    },
    onError: (err, vars) => {
      toast.error(err instanceof ApiError ? err.message : 'Something went wrong. Try again.')
      onError?.(err, vars)
    },
  })
}
