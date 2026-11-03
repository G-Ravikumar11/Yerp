import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { createStore, del as idbDel, get as idbGet, set as idbSet } from 'idb-keyval'
import { sendFile } from '@/api/files'
import { attachBillPhoto } from '@/api/sitecash'
import { ApiError, api, apiUrl } from '@/lib/api'
import { queryClient } from '@/lib/query'
import { personKey, personName } from '@/lib/session'
import { toast } from './toast'

/**
 * What the server says when an edit was made on a copy somebody else has since changed (see core/versions.py). The queue
 * knows it by these words, so it is the one place they are written down.
 */
export const CONFLICT_TEXT = 'was changed by somebody else'

/** Pictures kept on this phone until the record they belong to exists, and then sent. */
export interface StoredFiles {
  /** Where each is kept (IndexedDB, apart from the app's cache, so signing out does not clear them). */
  keys: string[]
  /** Against a record in the file store (`type`, `id`), or the bill of a site cash expense. */
  via: 'attached' | 'bill'
  type?: string
  /** The record's number: known for an edit, else read from the reply of the request that makes it (`idFrom`, as 'diary.id'). */
  id?: number
  idFrom?: string
}

export interface QueuedRequest {
  id: string
  /** 'upload' is one picture on its way to a record an earlier item made. */
  kind?: 'request' | 'upload'
  method: 'POST' | 'PUT' | 'DELETE'
  url: string
  body?: unknown
  /** What it was, in words - "Measurement: 12.5 cum against 1.0". */
  label: string
  createdAt: number
  /** 'conflict': somebody else changed the same record meanwhile; the person says whose version stands. */
  status: 'waiting' | 'failed' | 'conflict'
  /** Why the server refused it. A refused change needs a person, not a retry. */
  error?: string
  /** Who made it (personKey). It is sent only while that person is signed in on this phone, and never as somebody else. */
  by?: string
  byName?: string
  files?: StoredFiles
  /** For an edit: the version of the record the person started from. The server refuses it if the record has moved on. */
  base?: string
}

type NewRequest = Pick<QueuedRequest, 'method' | 'url' | 'body' | 'label'> & { id?: string; files?: StoredFiles; base?: string }

interface OfflineState {
  online: boolean
  syncing: boolean
  queue: QueuedRequest[]
  setOnline: (online: boolean) => void
  enqueue: (req: NewRequest) => QueuedRequest
  discard: (id: string) => void
  /** Everything, and the pictures kept for it: what the website does at sign-out. */
  clearQueue: () => void
  retry: (id: string) => void
  /** After a conflict: keep what this person entered over what is there now. */
  keepMine: (id: string) => void
  flush: () => Promise<void>
}

const uid = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`

/** A failure that means "no connection" rather than "the server said no". */
function isNetworkFailure(e: unknown) {
  return !(e instanceof ApiError) || e.status >= 500 || e.status === 408 || e.status === 429
}

/* --- Pictures kept on the phone ---------------------------------------------------------------------------------- */

// Their own store, so clearing the app's cache (signing out, a new person) leaves a picture waiting to go up where it is.
const fileStore = typeof indexedDB === 'undefined' ? undefined : createStore('yerp-offline-files', 'files')

/** Keep pictures on this phone; the keys to find them again. */
export async function keepFiles(files: File[]): Promise<string[]> {
  const keys: string[] = []
  for (const f of files) {
    const key = `file-${uid()}`
    await idbSet(key, f, fileStore)
    keys.push(key)
  }
  return keys
}
const takeFile = (key: string) => idbGet<File>(key, fileStore)
const dropFiles = (keys: string[] = []) => Promise.all(keys.map((k) => idbDel(k, fileStore).catch(() => undefined)))

/** Who may see and send this item: whoever made it. Items from before the person was recorded are the current person's. */
export const isMine = (q: QueuedRequest, me: string) => !q.by || q.by === me

/** One picture, sent to the record that now exists. Throws as the server (or the connection) did. */
async function sendStored(item: QueuedRequest) {
  const f = item.files
  const key = f?.keys[0]
  if (!f || !key || !f.id) throw new ApiError(400, 'There is nothing to send for this picture.')
  const file = await takeFile(key)
  if (!file) throw new ApiError(410, 'The picture is no longer on this phone. Take it again.')
  if (f.via === 'bill') await attachBillPhoto(f.id, file, item.id)
  else await sendFile(file, f.type ?? '', f.id, {}, item.id)
  await dropFiles(f.keys)
}

/** A value inside a reply, by a dotted path: 'diary.id'. */
const pick = (data: unknown, path: string): number | undefined => {
  let cur: unknown = data
  for (const part of path.split('.')) cur = (cur as Record<string, unknown> | null | undefined)?.[part]
  return typeof cur === 'number' ? cur : undefined
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
        const item: QueuedRequest = { ...req, id: req.id ?? uid(), kind: 'request', createdAt: Date.now(), status: 'waiting', by: personKey() || undefined, byName: personName() || undefined }
        set((s) => ({ queue: [...s.queue, item] }))
        return item
      },

      discard: (id) => {
        void dropFiles(get().queue.find((q) => q.id === id)?.files?.keys)
        set((s) => ({ queue: s.queue.filter((q) => q.id !== id) }))
      },

      clearQueue: () => {
        void dropFiles(get().queue.flatMap((q) => q.files?.keys ?? []))
        set({ queue: [] })
      },

      retry: (id) => {
        set((s) => ({ queue: s.queue.map((q) => (q.id === id ? { ...q, status: 'waiting', error: undefined } : q)) }))
        void get().flush()
      },

      keepMine: (id) => {
        // Sent again without the version it started from, so it replaces what is there now.
        set((s) => ({ queue: s.queue.map((q) => (q.id === id ? { ...q, status: 'waiting', error: undefined, base: undefined } : q)) }))
        void get().flush()
      },

      /**
       * Send what is waiting for the person signed in, oldest first and one at a time - a later change may depend on an
       * earlier one. Somebody else's items stay where they are until that person signs in. Stops at the first sign the
       * connection is gone; a request the server refuses is marked, kept and skipped so one bad entry does not hold the rest.
       */
      flush: async () => {
        if (get().syncing || !get().online) return
        const me = personKey()
        if (!me) return
        set({ syncing: true })
        let sent = 0
        try {
          for (;;) {
            const item = get().queue.find((q) => q.status === 'waiting' && isMine(q, me))
            if (!item) break
            try {
              // The same key it was first sent with: if that first try did reach the server, this one is answered, not made again.
              if (item.kind === 'upload') await sendStored(item)
              else {
                const result = await api<unknown>(item.url, {
                  method: item.method,
                  body: item.body,
                  headers: { 'Idempotency-Key': item.id, ...(item.base ? { 'X-Base-Version': item.base } : {}) },
                })
                if (item.files) {
                  // The record exists now: each picture kept for it becomes an item of its own, so one that fails does not hold the others.
                  const id = item.files.id ?? (item.files.idFrom ? pick(result, item.files.idFrom) : undefined)
                  const uploads: QueuedRequest[] = id
                    ? item.files.keys.map((key, i) => ({ id: `${item.id}-p${i}`, kind: 'upload', method: 'POST', url: '', label: `Photo for ${item.label}`, createdAt: Date.now(), status: 'waiting', by: item.by, byName: item.byName, files: { ...item.files!, keys: [key], id } }))
                    : []
                  if (!id) void dropFiles(item.files.keys)
                  set((s) => ({ queue: [...s.queue.filter((q) => q.id !== item.id), ...uploads] }))
                  if (!id) toast.error(`${item.label} was sent, but its photos could not be attached.`)
                  sent++
                  continue
                }
              }
              set((s) => ({ queue: s.queue.filter((q) => q.id !== item.id) }))
              sent++
            } catch (e) {
              if (isNetworkFailure(e)) {
                set({ online: false })
                break
              }
              if (e instanceof ApiError && e.status === 401) break
              const message = e instanceof ApiError ? e.detail || e.message : 'Refused'
              if (e instanceof ApiError && e.status === 409 && message.includes(CONFLICT_TEXT)) {
                set((s) => ({ queue: s.queue.map((q) => (q.id === item.id ? { ...q, status: 'conflict', error: message } : q)) }))
                toast.info(`${item.label}: somebody else changed it meanwhile. Choose whose version stands.`)
                continue
              }
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
      const res = await fetch(apiUrl('/api/health'), { cache: 'no-store' })
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

interface SendOptions {
  /** Pictures that belong to the record this makes or edits. Kept on the phone with the request if it has to wait. */
  files?: { items: File[]; via: StoredFiles['via']; type?: string; id?: number; idFrom?: string }
  /** For an edit: the version of the record the person started from. */
  base?: string
}

/**
 * Send a change now, or keep it for later. With no connection - known
 * (the browser says offline) or discovered (the request could not leave) -
 * the change goes on the queue and the caller is told so. A refusal from the
 * server is never queued: that is an answer, not an absence.
 * When it is kept, so are its pictures; when it is sent, the caller sends them itself, as before.
 */
export async function sendOrQueue<T>(req: Pick<QueuedRequest, 'method' | 'url' | 'body' | 'label'>, options: SendOptions = {}): Promise<{ queued: true } | { queued: false; result: T }> {
  const state = useOffline.getState()
  // One key for this change however many times it is sent: a reply lost on a weak signal looks like a request that
  // never arrived, and sending it again later must not make it twice.
  const id = uid()
  // The version an edit started from is sent only when it was kept and sent later: saved straight away, as before, the last save wins.
  const headers: Record<string, string> = { 'Idempotency-Key': id }

  const keep = async () => {
    let files: StoredFiles | undefined
    if (options.files?.items.length) {
      try {
        files = { keys: await keepFiles(options.files.items), via: options.files.via, type: options.files.type, id: options.files.id, idFrom: options.files.idFrom }
      } catch {
        toast.error('The photos could not be kept on this phone. Add them again once the day has gone up.')
      }
    }
    useOffline.getState().enqueue({ ...req, id, files, base: options.base })
  }

  if (!state.online) {
    await keep()
    return { queued: true }
  }
  try {
    return { queued: false, result: await api<T>(req.url, { method: req.method, body: req.body, headers }) }
  } catch (e) {
    if (e instanceof ApiError) throw e
    useOffline.getState().setOnline(false)
    await keep()
    return { queued: true }
  }
}
