import { useEffect, useState } from 'react'
import { Button, Field, Input } from '@/components/ui'
import { api } from '@/lib/api'
import { AuthLayout, Notice, nextTarget } from './AuthLayout'

const ERRORS: Record<string, string> = {
  auth_failed: 'Authentication failed. Please try again.',
  google_failed: 'Google sign-in did not complete. Try again.',
  google_no_email: 'Google did not share an email address.',
  google_unverified: 'That Google address is not verified.',
  google_unknown: 'No account here uses that Google address. Ask whoever set up your access.',
  account_disabled: 'That account has been disabled.',
  google_unconfigured: 'Google sign-in is not set up on this server yet.',
  gmail_sign_in_first: 'Sign in first, then connect Gmail from inside the app.',
}

const STEPS: [string, string][] = [
  ['Tender & estimate', 'Rates built up from material, labour and plant. Winning it opens the order.'],
  ['Work orders', 'Received from the client, issued to the contractors. Numbered, approved, printed.'],
  ['Measurement book', 'No × L × B × D, deductions for openings, both directions.'],
  ['RA bills', 'Retention, advance, GST split by place of supply, TDS, labour cess, in the order they are made.'],
  ['Store, site diary, profit', 'Goods in, three-way match, issues at cost, mandays and plant, margin per project.'],
]

const go = (to: string) => window.location.assign(to)

/** One door for the whole business: the server decides whether the address is the account holder's or a member of staff's. */
export default function LoginPage() {
  const params = new URLSearchParams(window.location.search)
  const code = params.get('error')
  const [error, setError] = useState(code ? (ERRORS[code] ?? 'Something went wrong. Please try again.') : '')
  const [company, setCompany] = useState('')
  const [google, setGoogle] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api<{ company_name?: string }>('/api/public/brand', { quiet: true }).then((b) => b?.company_name && setCompany(b.company_name)).catch(() => undefined)
    api<{ configured?: boolean }>('/api/auth/google/status', { quiet: true }).then((d) => setGoogle(!!d?.configured)).catch(() => undefined)
    if (params.get('signedout')) {
      // Arrived from Sign out: end whatever sign-in this browser still holds, and show the form.
      for (const u of ['/api/client/logout', '/api/employee/auth/logout', '/api/portal/logout']) void fetch(u, { method: 'POST' }).catch(() => undefined)
      return
    }
    // Already signed in: go straight on.
    void (async () => {
      for (const [url, to] of [['/api/client/me', nextTarget('/next/')], ['/api/employee/auth/me', nextTarget('/next/')], ['/api/superadmin/me', '/next/superadmin']]) {
        const r = await fetch(url).catch(() => null)
        if (r?.ok) return go(to)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim() || !password) return setError('Enter your email and password.')
    setBusy(true)
    setError('')
    try {
      const owner = await api<{ is_onboarded?: boolean }>('/api/client/login', { method: 'POST', body: { email: email.trim(), password }, quiet: true }).catch(() => null)
      if (owner) return go(owner.is_onboarded === false ? nextTarget('/next/onboard') : nextTarget('/next/'))
      const staff = await api('/api/employee/auth/login', { method: 'POST', body: { email: email.trim(), password, device_info: navigator.userAgent.slice(0, 200) }, quiet: true }).catch(() => null)
      if (staff) return go(nextTarget('/next/'))
      setError('That email and password did not match an account.')
    } finally {
      setBusy(false)
    }
  }

  const pitch = (
    <section aria-label="About Y ERP" className="hidden flex-col justify-between bg-gradient-to-br from-slate-900 via-slate-800 to-blue-900 p-10 text-slate-200 md:flex">
      <div>
        <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-blue-300">Civil contracting ERP</p>
        <h2 className="mb-2 mt-3 text-3xl font-extrabold leading-tight text-white">From the tender to the money, in one place.</h2>
        <p className="max-w-[34ch] text-sm text-slate-300">Every link of a contract, and each one feeds the next. Nothing is typed twice, and nothing lives in a spreadsheet beside it.</p>
        {company && <p className="mt-2 text-sm text-blue-200">The system of record for {company}.</p>}
        <ol className="mt-6 grid gap-3">
          {STEPS.map(([head, text], i) => (
            <li key={head} className="grid grid-cols-[30px_1fr] items-start gap-2.5 text-sm">
              <span className="grid size-6 place-items-center rounded-lg bg-blue-300/15 text-xs font-bold text-blue-200">{i + 1}</span>
              <span><b className="text-white">{head}</b><small className="block text-xs text-slate-400">{text}</small></span>
            </li>
          ))}
        </ol>
      </div>
      <p className="mt-7 text-xs text-slate-400"><b className="text-slate-200">No spreadsheets.</b> Grids paste and walk like a sheet, every table sorts and totals, every bill has a page that prints.</p>
    </section>
  )

  return (
    <AuthLayout title="Y ERP" subtitle="Sign in to your account" aside={pitch}>
      {error && <Notice tone="error">{error}</Notice>}
      <form onSubmit={submit} className="grid gap-4">
        <Field label="Email address" htmlFor="email"><Input id="email" type="email" autoComplete="username" autoFocus required placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password" htmlFor="password"><Input id="password" type="password" autoComplete="current-password" required placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <Button type="submit" loading={busy} className="w-full">Sign in</Button>
      </form>
      {google && (
        <>
          <div className="my-5 flex items-center gap-3 text-xs uppercase text-muted-foreground"><span className="h-px flex-1 bg-border" />or<span className="h-px flex-1 bg-border" /></div>
          <Button type="button" variant="outline" className="w-full" onClick={() => go('/api/auth/google/start?next=' + encodeURIComponent(nextTarget('/next/')))}>Continue with Google</Button>
        </>
      )}
      <p className="mt-5 text-center text-sm"><a className="text-muted-foreground hover:text-primary" href="/">&larr; Back to website</a></p>
    </AuthLayout>
  )
}
