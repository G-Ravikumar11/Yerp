/** A failed call to the backend, carrying the message the server gave. */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Options = Omit<RequestInit, 'body'> & {
  body?: unknown
  /** A 401 is an expected answer here (asking who is signed in), not a session that has ended. */
  quiet?: boolean
}

/**
 * The one door to the FastAPI backend. Sends the session cookie, speaks JSON,
 * and turns the backend's `{ detail }` errors into an ApiError so screens can
 * show the server's own plain-language reason.
 */
export async function api<T = unknown>(path: string, { body, headers, quiet, ...init }: Options = {}): Promise<T> {
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  const res = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: { ...(body !== undefined && !isForm ? { 'Content-Type': 'application/json' } : {}), ...headers },
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  })

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
      typeof detail === 'string' ? detail : Array.isArray(detail) ? 'Some of what was entered is not valid.' : res.statusText
    if (res.status === 401 && !quiet && !location.pathname.startsWith('/login')) {
      // The session ended; the login page is still the current app's.
      window.dispatchEvent(new CustomEvent('yerp:unauthorised'))
    }
    throw new ApiError(res.status, message)
  }
  return data as T
}

export const get = <T>(path: string) => api<T>(path)
export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body ?? {} })
export const put = <T>(path: string, body?: unknown) => api<T>(path, { method: 'PUT', body })
export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' })
