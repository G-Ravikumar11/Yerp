import type { ReactNode } from 'react'

/** The plain page every sign-in style screen sits on: a centred card, nothing else. */
export function AuthLayout({ title, subtitle, mark = 'Y', children, aside }: { title: string; subtitle?: string; mark?: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-8">
      <div className={aside ? 'grid w-full max-w-4xl overflow-hidden rounded-2xl border border-border bg-card shadow-xl md:grid-cols-[1.15fr_1fr]' : 'w-full max-w-md rounded-2xl border border-border bg-card p-8 shadow-xl'}>
        {aside}
        <div className={aside ? 'p-8 sm:p-10' : undefined}>
          <div className="mb-7 text-center">
            <div className="mx-auto mb-3 grid size-14 place-items-center rounded-2xl bg-gradient-to-br from-primary to-primary/60 text-xl font-bold text-primary-foreground">{mark}</div>
            <h1 className="text-xl font-bold">{title}</h1>
            {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
          </div>
          {children}
        </div>
      </div>
    </main>
  )
}

export function Notice({ tone, children }: { tone: 'error' | 'success'; children: ReactNode }) {
  return (
    <p role={tone === 'error' ? 'alert' : 'status'} className={tone === 'error' ? 'mb-4 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2.5 text-sm text-danger' : 'mb-4 rounded-lg border border-success/40 bg-success/10 px-3 py-2.5 text-sm text-success'}>
      {children}
    </p>
  )
}

/** Only a path on this site may be gone to after signing in; anything else is ignored. */
export function nextTarget(fallback: string): string {
  const next = new URLSearchParams(window.location.search).get('next') || ''
  return next.startsWith('/') && !next.startsWith('//') ? next : fallback
}
