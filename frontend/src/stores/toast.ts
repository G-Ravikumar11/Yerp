import { create } from 'zustand'

export type ToastTone = 'success' | 'error' | 'info'
interface Toast {
  id: number
  tone: ToastTone
  message: string
  /** A button on the message ("Reload"), used or dismissed by the person. */
  action?: { label: string; onClick: () => void }
}

interface ToastState {
  toasts: Toast[]
  push: (tone: ToastTone, message: string, action?: Toast['action']) => void
  dismiss: (id: number) => void
}

let next = 1

export const useToasts = create<ToastState>((set) => ({
  toasts: [],
  push: (tone, message, action) => {
    const id = next++
    // A message stays until it is closed (the X): nothing disappears while it is being read. The newest five are kept.
    set((s) => ({ toasts: [...s.toasts.slice(-4), { id, tone, message, action }] }))
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
