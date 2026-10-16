import { create } from 'zustand'
import { ApiError } from '@/lib/api'
import { newRef } from '@/lib/errorCodes'
import type { ErrorKind } from '@/components/errors/ErrorPage'

/**
 * The error page shown over a screen when something the person did failed for a reason they cannot fix by changing
 * what they typed: the server broke or is busy, there is no connection, they have no access, or the record is gone.
 * Everyday mistakes in a form ("the name is needed") stay a short message beside the form, so nothing typed is lost.
 */
export interface ShownError { kind: ErrorKind; code: string; ref: string; message: string }

interface ErrorPageState {
  shown: ShownError | null
  show: (e: ShownError) => void
  clear: () => void
}

export const useErrorPage = create<ErrorPageState>((set) => ({
  shown: null,
  show: (shown) => set({ shown }),
  clear: () => set({ shown: null }),
}))

/** Which page a failure gets, or null when a short message beside the form is the right answer. */
export function pageFor(err: unknown): ShownError | null {
  if (err instanceof ApiError) {
    const c = err.code
    const kind: ErrorKind | null = c.startsWith('YE-SRV') ? 'server'
      : c.startsWith('YE-BUSY') ? 'busy'
      : c === 'YE-ACCESS-01' || c === 'YE-AUTH-05' ? 'forbidden'
      : c === 'YE-DATA-01' ? 'gone'
      : null
    return kind ? { kind, code: c, ref: err.ref, message: err.detail } : null
  }
  const offline = err instanceof TypeError || (typeof navigator !== 'undefined' && navigator.onLine === false)
  return offline ? { kind: 'offline', code: 'YE-NET', ref: '', message: '' } : { kind: 'crash', code: 'YE-APP', ref: newRef(), message: '' }
}
