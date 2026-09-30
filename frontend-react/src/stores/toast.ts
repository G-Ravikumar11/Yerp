import { create } from 'zustand'

export type ToastTone = 'success' | 'error' | 'info'
export interface Toast {
  id: number
  tone: ToastTone
  message: string
  /** A button on the message ("Reload"). A toast with one stays until it is used or dismissed. */
  action?: { label: string; onClick: () => void }
}

interface ToastState {
  toasts: Toast[]
  push: (tone: ToastTone, message: string, action?: Toast['action']) => void
  dismiss: (id: number) => void
}

let next = 1

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push: (tone, message, action) => {
    const id = next++
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, tone, message, action }] }))
    // Errors stay long enough to read; the rest get out of the way.
    if (!action) setTimeout(() => get().dismiss(id), tone === 'error' ? 8000 : 4000)
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

/** Callable from anywhere - a mutation's callback, a plain function. */
export const toast = {
  success: (message: string) => useToasts.getState().push('success', message),
  error: (message: string) => useToasts.getState().push('error', message),
  info: (message: string) => useToasts.getState().push('info', message),
  withAction: (message: string, label: string, onClick: () => void) => useToasts.getState().push('info', message, { label, onClick }),
}
