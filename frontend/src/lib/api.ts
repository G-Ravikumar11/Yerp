import { noteAnswer } from './freshness'
import { codeFor, codeLine, showsCode } from './errorCodes'

/**
 * A failed call to the backend, carrying the message the server gave and its error code and reference.
 * `message` is what screens show: the server's words, followed by "(Error YE-SRV-01 · ref 7F3A9C21)" for a failure
 * (an input mistake shows its words alone). `detail` is the words without the code.
 */
export class ApiError extends Error {
  status: number
  code: string
  ref: string
  detail: string
  constructor(status: number, message: string, code?: string, ref?: string) {
    const c = code || codeFor(status)
    super(showsCode(c) ? `${message} (${codeLine(c, ref)})` : message)
    this.status = status
    this.code = c
    this.ref = ref || ''
    this.detail = message
  }
}

/** What to say when the server gave no message of its own (over HTTP/2 the status text is empty, so the toast was blank). */
function plainStatus(status: number, text: string): string {
  if (text) return text
  if (status === 502 || status === 503 || status === 504) return 'The server took too long to answer or was restarting. Nothing may have been saved: wait a minute, reload and check before trying again.'
  if (status === 413) return 'That is too large to send. Split it and try again.'
  if (status === 429) return 'Too many requests at once. Wait a moment and try again.'
  if (status >= 500) return 'The server had a problem with that. Try again, and tell us if it keeps happening.'
  return `That did not work (error ${status}).`
}

type Options = Omit<RequestInit, 'body'> & {
  body?: unknown
  /** A 401 is an expected answer here (asking who is signed in), not a session that has ended. */
  quiet?: boolean
}

/**
 * Resolves an API or backend path against the configured backend base URL
 * (e.g. from VITE_API_BASE_URL when running inside Capacitor) or leaves
 * it relative when running directly in the browser served alongside FastAPI.
 */
export function apiUrl(path: string): string {
  if (!path) return ''
  if (/^https?:\/\//i.test(path)) return path
  const base = (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/$/, '')
  if (!base) return path
  return path.startsWith('/') ? `${base}${path}` : `${base}/${path}`
}

/**
 * The one door to the FastAPI backend. Sends the session cookie, speaks JSON,
 * and turns the backend's `{ detail }` errors into an ApiError so screens can
 * show the server's own plain-language reason.
 */
export async function api<T = unknown>(path: string, { body, headers, quiet, ...init }: Options = {}): Promise<T> {
  const method = (init.method || 'GET').toUpperCase()
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  const targetUrl = apiUrl(path)
  const res = await fetch(targetUrl, {
    credentials: 'include',
    ...init,
    headers: { ...(body !== undefined && !isForm ? { 'Content-Type': 'application/json' } : {}), ...headers },
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  })
  noteAnswer(res)

  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }

  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail
    const message =
      typeof detail === 'string' ? detail : Array.isArray(detail) ? 'Some of what was entered is not valid.' : plainStatus(res.status, res.statusText)
    if (res.status === 401 && !quiet && !/^\/(next\/)?(login|reset-password|superadmin\/login)/.test(location.pathname)) {
      // The session ended; the login page is still the current app's.
      window.dispatchEvent(new CustomEvent('yerp:unauthorised'))
    }
    const info = (data as { code?: unknown; ref?: unknown } | null) ?? {}
    throw new ApiError(res.status, message, typeof info.code === 'string' ? info.code : undefined, typeof info.ref === 'string' ? info.ref : res.headers.get('X-Error-Ref') || undefined)
  }
  // A record is gone: every screen that kept a copy of a list must stop showing it (App.tsx).
  if (method === 'DELETE' || /\/bulk-delete$/.test(path)) window.dispatchEvent(new Event('yerp:deleted'))
  return data as T
}

export const get = <T>(path: string) => api<T>(path)
export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body ?? {} })
export const put = <T>(path: string, body?: unknown) => api<T>(path, { method: 'PUT', body })
export const patch = <T>(path: string, body?: unknown) => api<T>(path, { method: 'PATCH', body })
export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' })
