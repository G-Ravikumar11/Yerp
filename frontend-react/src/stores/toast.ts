import { create } from 'zustand'

export type ToastTone = 'success' | 'error' | 'info'
export interface Toast {
  id: number
  tone: ToastTone
  message: string
}

interface ToastState {
  toasts: Toast[]
  push: (tone: ToastTone, message: string) => void
  dismiss: (id: number) => void
}

let next = 1

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push: (tone, message) => {
    const id = next++
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, tone, message }] }))
    // Errors stay long enough to read; the rest get out of the way.
    setTimeout(() => get().dismiss(id), tone === 'error' ? 8000 : 4000)
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

/** Callable from anywhere - a mutation's callback, a plain function. */
export const toast = {
  success: (message: string) => useToasts.getState().push('success', message),
  error: (message: string) => useToasts.getState().push('error', message),
  info: (message: string) => useToasts.getState().push('info', message),
}
