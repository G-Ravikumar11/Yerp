import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Copy, Home, RotateCcw, Undo2 } from 'lucide-react'
import { codeLine } from '@/lib/errorCodes'
import { cn } from '@/lib/utils'

/** The kinds of failure that get a whole page, each with its big number, its words and its glow. */
export const KINDS = {
  notFound: { big: '404', title: 'Page not found', text: 'This page has wandered off the site plan. The address may be old, or it was never here.', glow: '#3b82f6' },
  forbidden: { big: '403', title: 'No access here', text: 'Your access does not include this. Ask the Master to grant it.', glow: '#8b5cf6' },
  server: { big: '500', title: 'Something broke', text: 'The server hit a problem with that. It has been noted under the ref below - nothing was lost on this screen.', glow: '#ef4444' },
  busy: { big: '503', title: 'Server busy', text: 'The server is busy or restarting. Wait a minute, then try again.', glow: '#f59e0b' },
  offline: { big: 'Offline', title: 'No connection', text: 'The app could not reach the server. Check the connection; anything you entered is kept on this device.', glow: '#06b6d4' },
  crash: { big: 'Oops', title: 'This screen broke', text: 'Something on this screen went wrong. Nothing you entered elsewhere was lost.', glow: '#f97316' },
  gone: { big: '404', title: 'It is not there any more', text: 'What you were working on was removed, perhaps by someone else. Go back and reload.', glow: '#3b82f6' },
} as const
export type ErrorKind = keyof typeof KINDS

/** A safety helmet adrift with its bolts and a blueprint, in a glow - the picture on every error page. */
function Adrift({ glow }: { glow: string }) {
  return (
    <div className="relative grid aspect-square w-full max-w-[22rem] place-items-center">
      <div className="absolute inset-[8%] rounded-full opacity-70 blur-3xl" style={{ background: `radial-gradient(circle, ${glow} 0%, transparent 70%)` }} />
      <svg viewBox="0 0 240 240" className="error-float relative w-[78%]" aria-hidden>
        <defs>
          <linearGradient id="ep-hat" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#ffd34d" />
            <stop offset="1" stopColor="#f5a300" />
          </linearGradient>
          <linearGradient id="ep-paper" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#dbeafe" />
            <stop offset="1" stopColor="#93c5fd" />
          </linearGradient>
        </defs>
        {/* the blueprint, drifting behind */}
        <g transform="rotate(-14 150 150)">
          <rect x="112" y="118" width="86" height="64" rx="5" fill="url(#ep-paper)" />
          <path d="M122 132h40M122 142h60M122 152h30M168 132v38h20" stroke="#2563eb" strokeWidth="2.4" fill="none" strokeLinecap="round" opacity="0.8" />
        </g>
        {/* the helmet */}
        <g transform="rotate(-10 110 108)">
          <path d="M52 118c0-38 26-66 60-66s60 28 60 66z" fill="url(#ep-hat)" />
          <path d="M100 54c-2 18-2 44 0 64M124 54c2 18 2 44 0 64" stroke="#e08e00" strokeWidth="5" fill="none" opacity="0.7" />
          <rect x="38" y="114" width="148" height="14" rx="7" fill="#f5a300" />
          <rect x="38" y="114" width="148" height="5" rx="2.5" fill="#ffe08a" opacity="0.8" />
          <path d="M70 84c6-16 18-26 32-28" stroke="#fff6cc" strokeWidth="5" fill="none" strokeLinecap="round" opacity="0.65" />
        </g>
        {/* bolts and a nut, adrift */}
        <g fill="#c7d2fe">
          <g transform="rotate(30 40 60)"><rect x="36" y="46" width="8" height="26" rx="2" /><rect x="31" y="42" width="18" height="7" rx="2" /></g>
          <g transform="rotate(-40 200 62)"><rect x="196" y="50" width="7" height="22" rx="2" /><rect x="192" y="46" width="15" height="6" rx="2" /></g>
          <path d="M60 182l9-5 9 5v10l-9 5-9-5z" />
          <circle cx="69" cy="187" r="3.5" fill="#0b1020" />
        </g>
        {/* stars */}
        <g fill="#fcd34d">
          <path d="M186 104l2.5 5 5 2.5-5 2.5-2.5 5-2.5-5-5-2.5 5-2.5z" className="error-twinkle" />
          <path d="M30 140l2 4 4 2-4 2-2 4-2-4-4-2 4-2z" className="error-twinkle" style={{ animationDelay: '0.9s' }} />
          <circle cx="160" cy="34" r="2.5" className="error-twinkle" style={{ animationDelay: '1.6s' }} />
        </g>
      </svg>
    </div>
  )
}

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
        'error-page relative isolate overflow-hidden bg-[#05070d] text-white',
        overlay ? 'fixed inset-0 z-[75] overflow-y-auto' : 'min-h-[calc(100dvh-9rem)] rounded-3xl',
      )}
    >
      <div className="mx-auto grid min-h-full max-w-6xl items-center gap-10 px-6 py-14 md:grid-cols-2 md:px-12">
        <div className="text-center md:text-left">
          <h1 className="font-display text-6xl font-bold tracking-[0.12em] sm:text-7xl">
            {k.big}
            {/^\d+$/.test(k.big) && <span className="text-white/70">-error</span>}
          </h1>
          <p className="mt-4 text-2xl font-semibold uppercase tracking-[0.08em] sm:text-3xl">{k.title}</p>
          <p className="mx-auto mt-3 max-w-md text-[15px] text-white/60 md:mx-0">{k.text}</p>
          {message && message !== k.text && <p className="mx-auto mt-2 max-w-md text-[13px] text-white/45 md:mx-0">{message}</p>}
          <div className="mt-8 flex flex-wrap justify-center gap-3 md:justify-start">
            {onBack && (
              <button type="button" onClick={onBack} className="inline-flex items-center gap-2 rounded-full border border-white/25 px-5 py-2.5 text-sm hover:border-white/60">
                <Undo2 className="size-4" /> Go back
              </button>
            )}
            {onRetry && (
              <button type="button" onClick={onRetry} className="inline-flex items-center gap-2 rounded-full border border-white/25 px-5 py-2.5 text-sm hover:border-white/60">
                <RotateCcw className="size-4" /> Try again
              </button>
            )}
            <Link to="/" onClick={onBack} className="inline-flex items-center gap-2 rounded-full border border-[color:var(--primary)] px-5 py-2.5 text-sm text-white hover:bg-[color:var(--primary)]/15">
              <Home className="size-4" /> Back to Home
            </Link>
          </div>
          {line && (
            <button
              type="button"
              title="Copy, to send to support"
              onClick={() => {
                void navigator.clipboard?.writeText(`${line} on ${location.pathname}`)
                setCopied(true)
              }}
              className="mt-8 inline-flex items-center gap-2 rounded-full bg-white/5 px-3 py-1 font-mono text-[12px] text-white/55 ring-1 ring-white/10 hover:text-white"
            >
              {line} <Copy className="size-3" /> <span className="font-sans">{copied ? 'Copied' : ''}</span>
            </button>
          )}
        </div>
        <div className="flex justify-center">
          <Adrift glow={k.glow} />
        </div>
      </div>
    </div>
  )
}
