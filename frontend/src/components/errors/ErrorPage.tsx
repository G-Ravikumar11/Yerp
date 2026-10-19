import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Copy, Home, RotateCcw, Undo2 } from 'lucide-react'
import { codeLine } from '@/lib/errorCodes'
import { cn } from '@/lib/utils'

/** The kinds of failure that get a whole page, each with its code and its words. */
export const KINDS = {
  notFound: { big: '404', title: 'Page not found', text: 'This page has wandered off the site plan. The address may be old, or it was never here.' },
  forbidden: { big: '403', title: 'No access here', text: 'Your access does not include this. Ask the Master to grant it.' },
  server: { big: '500', title: 'Something broke', text: 'The server hit a problem with that. It has been noted under the ref below - nothing was lost on this screen.' },
  busy: { big: '503', title: 'Server busy', text: 'The server is busy or restarting. Wait a minute, then try again.' },
  offline: { big: 'Offline', title: 'No connection', text: 'The app could not reach the server. Check the connection; anything you entered is kept on this device.' },
  crash: { big: 'Oops', title: 'This screen broke', text: 'Something on this screen went wrong. Nothing you entered elsewhere was lost.' },
  gone: { big: '404', title: 'It is not there any more', text: 'What you were working on was removed, perhaps by someone else. Go back and reload.' },
} as const
export type ErrorKind = keyof typeof KINDS

/**
 * A whole page for a failure: the big number, what happened in plain words, the way back, and the error code and
 * ref to give support. `onBack` closes it (the screen underneath, with whatever was typed, is still there);
 * `onRetry` tries again. Shown inside the app (page not found, a broken screen) or over it (a save that failed).
 */
export function ErrorPage({ kind, code, errorRef, message, onBack, onRetry, overlay = false }: {
  kind: ErrorKind
  code?: string
  errorRef?: string
  /** The server's own words, shown under the general explanation when they add something. */
  message?: string
  onBack?: () => void
  onRetry?: () => void
  overlay?: boolean
}) {
  const k = KINDS[kind]
  const [copied, setCopied] = useState(false)
  const line = code ? codeLine(code, errorRef) : ''
  return (
    <div
      role="alert"
      className={cn(
        'error-page bg-background text-foreground',
        overlay ? 'fixed inset-0 z-[75] overflow-y-auto' : 'min-h-[calc(100dvh-9rem)] rounded-lg',
      )}
    >
      <div className="mx-auto flex min-h-full max-w-xl flex-col items-center justify-center px-6 py-16 text-center">
        <AlertTriangle className="size-10 text-danger" aria-hidden />
        <p className="mt-4 font-mono text-sm text-muted-foreground">{k.big}</p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">{k.title}</h1>
        <p className="mt-2 text-[15px] text-muted-foreground">{k.text}</p>
        {message && message !== k.text && <p className="mt-2 text-[13px] text-muted-foreground">{message}</p>}
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link to="/" onClick={onBack} className="inline-flex items-center gap-2 rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            <Home className="size-4" /> Go Home
          </Link>
          {onBack && (
            <button type="button" onClick={onBack} className="inline-flex items-center gap-2 rounded-md border border-input px-5 py-2.5 text-sm hover:bg-muted">
              <Undo2 className="size-4" /> Go back
            </button>
          )}
          {onRetry && (
            <button type="button" onClick={onRetry} className="inline-flex items-center gap-2 rounded-md border border-input px-5 py-2.5 text-sm hover:bg-muted">
              <RotateCcw className="size-4" /> Try again
            </button>
          )}
        </div>
        {line && (
          <button
            type="button"
            title="Copy, to send to support"
            onClick={() => {
              void navigator.clipboard?.writeText(`${line} on ${location.pathname}`)
              setCopied(true)
            }}
            className="mt-8 inline-flex items-center gap-2 rounded-md bg-muted px-3 py-1 font-mono text-[12px] text-muted-foreground hover:text-foreground"
          >
            {line} <Copy className="size-3" /> <span className="font-sans">{copied ? 'Copied' : ''}</span>
          </button>
        )}
      </div>
    </div>
  )
}
