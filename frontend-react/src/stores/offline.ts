import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { ApiError, api } from '@/lib/api'
import { queryClient } from '@/lib/query'
import { toast } from './toast'

export interface QueuedRequest {
  id: string
  method: 'POST' | 'PUT' | 'DELETE'
  url: string
  body?: unknown
  /** What it was, in words - "Measurement: 12.5 cum against 1.0". */
  label: string
  createdAt: number
  status: 'waiting' | 'failed'
  /** Why the server refused it. A refused change needs a person, not a retry. */
  error?: string
}

interface OfflineState {
  online: boolean
  syncing: boolean
  queue: QueuedRequest[]
  setOnline: (online: boolean) => void
  enqueue: (req: Pick<QueuedRequest, 'method' | 'url' | 'body' | 'label'>) => QueuedRequest
  discard: (id: string) => void
  retry: (id: string) => void
  flush: () => Promise<void>
}

const uid = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`

/** A failure that means "no connection" rather than "the server said no". */
export function isNetworkFailure(e: unknown) {
  return !(e instanceof ApiError) || e.status >= 500 || e.status === 408 || e.status === 429
}

export const useOffline = create<OfflineState>()(
  persist(
    (set, get) => ({
      online: typeof navigator === 'undefined' ? true : navigator.onLine,
      syncing: false,
      queue: [],

      setOnline: (online) => {
        set({ online })
        if (online) void get().flush()
      },

      enqueue: (req) => {
        const item: QueuedRequest = { ...req, id: uid(), createdAt: Date.now(), status: 'waiting' }
        set((s) => ({ queue: [...s.queue, item] }))
        return item
      },

      discard: (id) => set((s) => ({ queue: s.queue.filter((q) => q.id !== id) })),

      retry: (id) => {
        set((s) => ({ queue: s.queue.map((q) => (q.id === id ? { ...q, status: 'waiting', error: undefined } : q)) }))
        void get().flush()
      },

      /**
       * Send what is waiting, oldest first and one at a time - a later change
       * may depend on an earlier one. Stops at the first sign the connection
       * is gone; a request the server refuses is marked, kept and skipped so
       * one bad entry does not hold the rest.
       */
      flush: async () => {
        if (get().syncing || !get().online) return
        set({ syncing: true })
        let sent = 0
        try {
          for (const item of get().queue.filter((q) => q.status === 'waiting')) {
            try {
              await api(item.url, { method: item.method, body: item.body })
              set((s) => ({ queue: s.queue.filter((q) => q.id !== item.id) }))
              sent++
            } catch (e) {
              if (isNetworkFailure(e)) {
                set({ online: false })
                break
              }
              if (e instanceof ApiError && e.status === 401) break
              const message = e instanceof ApiError ? e.message : 'Refused'
              set((s) => ({ queue: s.queue.map((q) => (q.id === item.id ? { ...q, status: 'failed', error: message } : q)) }))
              toast.error(`${item.label} was not accepted: ${message}`)
            }
          }
        } finally {
          set({ syncing: false })
        }
        if (sent) {
          toast.success(`${sent} change${sent === 1 ? '' : 's'} sent`)
          await queryClient.invalidateQueries()
        }
      },
    }),
    { name: 'yerp-offline', partialize: (s) => ({ queue: s.queue }) },
  ),
)

/** Wire the browser's own connection events to the store. Called once. */
export function watchConnection() {
  const on = () => useOffline.getState().setOnline(true)
  const off = () => useOffline.getState().setOnline(false)
  window.addEventListener('online', on)
  window.addEventListener('offline', off)
  if (navigator.onLine) void useOffline.getState().flush()

  // A request can fail while the browser still believes it is online (a
  // dropped mobile signal, a server restarting). Ask the server itself now
  // and then, so a queue never waits on an event that will not come.
  const probe = window.setInterval(async () => {
    const s = useOffline.getState()
    if (s.online && !s.queue.length) return
    try {
      const res = await fetch('/api/health', { cache: 'no-store' })
      if (res.ok && !s.online) s.setOnline(true)
      else if (res.ok && s.queue.some((q) => q.status === 'waiting')) void s.flush()
    } catch {
      if (s.online) s.setOnline(false)
    }
  }, 15_000)

  return () => {
    window.removeEventListener('online', on)
    window.removeEventListener('offline', off)
    window.clearInterval(probe)
  }
}

/**
 * Send a change now, or keep it for later. With no connection - known
 * (the browser says offline) or discovered (the request could not leave) -
 * the change goes on the queue and the caller is told so. A refusal from the
 * server is never queued: that is an answer, not an absence.
 */
export async function sendOrQueue<T>(req: Pick<QueuedRequest, 'method' | 'url' | 'body' | 'label'>): Promise<{ queued: true } | { queued: false; result: T }> {
  const state = useOffline.getState()
  if (!state.online) {
    state.enqueue(req)
    return { queued: true }
  }
  try {
    return { queued: false, result: await api<T>(req.url, { method: req.method, body: req.body }) }
  } catch (e) {
    if (e instanceof ApiError) throw e
    useOffline.getState().setOnline(false)
    useOffline.getState().enqueue(req)
    return { queued: true }
  }
}
