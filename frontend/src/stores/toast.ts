import { create } from 'zustand'

export type ToastTone = 'success' | 'error' | 'info'
interface Toast {
  id: number
  tone: ToastTone
  message: string
  /** Goes by itself after a few seconds: a success, or a passing note. Everything else stays until it is closed. */
  fades: boolean
  /** A button on the message ("Reload"), used or dismissed by the person. */
  action?: { label: string; onClick: () => void }
}

interface ToastState {
  toasts: Toast[]
  push: (tone: ToastTone, message: string, opts?: { action?: Toast['action']; fades?: boolean }) => void
  dismiss: (id: number) => void
  /** The pointer or keyboard is on it: it does not fade while being read. */
  hold: (id: number) => void
  /** Let go of: it fades a few seconds later. */
  release: (id: number) => void
}

/** How long a success stays on screen. */
export const FADE_MS = 4000

let next = 1
const timers = new Map<number, ReturnType<typeof setTimeout>>()
const stop = (id: number) => {
  clearTimeout(timers.get(id))
  timers.delete(id)
}

export const useToasts = create<ToastState>((set, get) => {
  const fadeLater = (id: number) => {
    stop(id)
    timers.set(id, setTimeout(() => get().dismiss(id), FADE_MS))
  }
  return {
    toasts: [],
    push: (tone, message, opts = {}) => {
      const id = next++
      // A success goes by itself. A failure, a warning and a notification stay until the person closes them (the X), so
      // nothing that matters disappears before it is read. A message with a button waits for the button. The newest five
      // are kept.
      const fades = !opts.action && (opts.fades ?? tone === 'success')
      set((s) => ({ toasts: [...s.toasts.slice(-4), { id, tone, message, fades, action: opts.action }] }))
      if (fades) fadeLater(id)
    },
    dismiss: (id) => {
      stop(id)
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    },
    hold: (id) => stop(id),
    release: (id) => {
      if (get().toasts.some((t) => t.id === id && t.fades)) fadeLater(id)
    },
  }
})

/** Callable from anywhere - a mutation's callback, a plain function. */
export const toast = {
  /** Done: says so, then goes. */
  success: (message: string) => useToasts.getState().push('success', message),
  /** Failed: stays until closed. */
  error: (message: string) => useToasts.getState().push('error', message),
  /** A warning or a notice to act on: stays until closed. */
  info: (message: string) => useToasts.getState().push('info', message),
  /** A passing note ("Getting the file..."): goes by itself like a success. */
  brief: (message: string) => useToasts.getState().push('info', message, { fades: true }),
  withAction: (message: string, label: string, onClick: () => void) => useToasts.getState().push('info', message, { action: { label, onClick } }),
}
