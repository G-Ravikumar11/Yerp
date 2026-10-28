import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Field, Input, Tabs } from '@/components/ui'
import { api, ApiError } from '@/lib/api'
import { AuthLayout, Notice, YahooMark } from '@/features/auth/AuthLayout'
import { CaptchaBox, type CaptchaValue } from '@/features/auth/CaptchaBox'
import { portalAcceptInvite, portalInvite, portalKeys, portalLogin, portalLogout, usePortalMe, type PortalInvite } from '@/api/portal'
import { Bills, Orders, Overview, Payments, SendInvoice, Statement } from './PortalTabs'

type Tab = 'overview' | 'orders' | 'bills' | 'payments' | 'statement' | 'send'

const GOOGLE_ERRORS: Record<string, string> = {
  yahoo_failed: 'Yahoo sign-in did not complete. Try again.',
  yahoo_no_email: 'Yahoo did not share an email address.',
  yahoo_unverified: 'That Yahoo address is not verified.',
  yahoo_unknown: 'No partner login uses that Yahoo address. Ask the office to open the portal to it.',
  yahoo_unconfigured: 'Yahoo sign-in is not set up on this server yet. Sign in with your email and password.',
  yahoo_denied: 'Yahoo sign-in was cancelled. Try again, or sign in with your email and password.',
  yahoo_state: 'That Yahoo sign-in did not start here, so it was stopped for your safety. Please try again.',
  yahoo_expired: 'That Yahoo sign-in took too long or was used already. Please try again.',
  google_retired: 'Sign in with Google is no longer offered. Continue with Yahoo, or sign in with your email and password.',
  account_disabled: 'This login is no longer open. Ask the office.',
}


/** A subcontractor's or supplier's own door: their orders, bills, payments and statement with the company. */
export default function PortalPage() {
  const params = new URLSearchParams(window.location.search)
  const token = params.get('invite')
  const me = usePortalMe()
  if (token && !me.data) return <InviteScreen token={token} />
  if (me.isLoading) return null
  if (!me.data) return <SignIn />
  return <PortalApp />
}

function SignIn() {
  const qc = useQueryClient()
  const code = new URLSearchParams(window.location.search).get('error')
  const [error, setError] = useState(code ? (GOOGLE_ERRORS[code] ?? 'Something went wrong. Try again.') : '')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [askCheck, setAskCheck] = useState(false)
  const [check, setCheck] = useState<CaptchaValue | null>(null)
  const [round, setRound] = useState(0)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (askCheck && !check) return setError('Complete the check, then sign in.')
    setBusy(true)
    setError('')
    try {
      await portalLogin(email, password, check)
      await qc.invalidateQueries({ queryKey: portalKeys.me })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not sign in.')
      // After several wrong tries the server asks for a check, and from then on every try needs a new one.
      if ((err instanceof ApiError && err.status === 428) || askCheck) { setAskCheck(true); setRound((n) => n + 1) }
    } finally {
      setBusy(false)
    }
  }
  return (
    <AuthLayout title="Partner portal" subtitle="For subcontractors and suppliers: your orders, bills, payments and statement." mark="P">
      {error && <Notice tone="error">{error}</Notice>}
      <form onSubmit={submit} className="grid gap-4">
        <Field label="Email" htmlFor="pl-email"><Input id="pl-email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password" htmlFor="pl-pass"><Input id="pl-pass" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        {askCheck && <CaptchaBox round={round} onChange={setCheck} />}
        <Button type="submit" loading={busy}>Sign in</Button>
      </form>
      <Button variant="outline" className="mt-3 w-full gap-2.5" onClick={() => window.location.assign('/api/auth/yahoo/start?who=portal')}><YahooMark /> Continue with Yahoo</Button>
      <p className="mt-4 text-xs text-muted-foreground">Forgotten your password? Ask the office for a new link.</p>
    </AuthLayout>
  )
}

function InviteScreen({ token }: { token: string }) {
  const qc = useQueryClient()
  const [invite, setInvite] = useState<PortalInvite | null | 'dead'>(null)
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [error, setError] = useState('')
  useEffect(() => { portalInvite(token).then(setInvite).catch((e) => { setInvite('dead'); setError(e instanceof ApiError ? e.message : 'Ask the office for a new one.') }) }, [token])
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (a !== b) return setError('The two passwords are not the same.')
    try {
      await portalAcceptInvite(token, a)
      window.history.replaceState(null, '', window.location.pathname)
      await qc.invalidateQueries({ queryKey: portalKeys.me })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not set it.')
    }
  }
  if (invite === null) return null
  if (invite === 'dead') return <AuthLayout title="This link has expired" mark="P"><Notice tone="error">{error}</Notice></AuthLayout>
  return (
    <AuthLayout title={`Welcome, ${invite.name || invite.party}`} subtitle={`${invite.company} has opened its partner portal to ${invite.party}. You will sign in as ${invite.email}.`} mark="P">
      {error && <Notice tone="error">{error}</Notice>}
      <form onSubmit={submit} className="grid gap-4">
        <Field label="Choose a password" htmlFor="pi-pass"><Input id="pi-pass" type="password" minLength={8} required autoComplete="new-password" value={a} onChange={(e) => setA(e.target.value)} /></Field>
        <Field label="Once more" htmlFor="pi-pass2"><Input id="pi-pass2" type="password" minLength={8} required autoComplete="new-password" value={b} onChange={(e) => setB(e.target.value)} /></Field>
        <Button type="submit">Set password and open</Button>
      </form>
      <Button variant="outline" className="mt-3 w-full gap-2.5" onClick={() => window.location.assign('/api/auth/yahoo/start?who=portal')}><YahooMark /> Or skip the password: continue with Yahoo</Button>
    </AuthLayout>
  )
}

function PortalApp() {
  const qc = useQueryClient()
  const me = usePortalMe().data!
  const [tab, setTab] = useState<Tab>('overview')
  useEffect(() => { document.title = `${me.company} · Partner portal` }, [me.company])
  const items = [
    { value: 'overview', label: 'Overview' }, { value: 'orders', label: 'Orders' }, { value: 'bills', label: 'Bills' },
    { value: 'payments', label: 'Payments' }, { value: 'statement', label: 'Statement' },
    ...(me.party_type === 'supplier' ? [{ value: 'send', label: 'Send an invoice' }] : []),
  ] as { value: Tab; label: string }[]
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
          <div><p className="text-lg font-bold">{me.party}</p><p className="text-xs text-muted-foreground">Your account with {me.company}{me.name ? ` · ${me.name}` : ''}</p></div>
          <Button variant="outline" size="sm" onClick={async () => { await portalLogout(); await qc.invalidateQueries({ queryKey: portalKeys.me }); qc.removeQueries({ queryKey: ['portal'], predicate: (q) => q.queryKey[1] !== 'me' }) }}>Sign out</Button>
        </div>
      </header>
      <div className="mx-auto max-w-5xl px-4 py-5">
        <Tabs label="Portal sections" items={items} value={tab} onChange={setTab} />
        <div className="mt-5">
          {tab === 'overview' && <Overview />}
          {tab === 'orders' && <Orders />}
          {tab === 'bills' && <Bills contractor={me.party_type === 'contractor'} />}
          {tab === 'payments' && <Payments />}
          {tab === 'statement' && <Statement />}
          {tab === 'send' && <SendInvoice />}
        </div>
      </div>
    </div>
  )
}
