import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Field, Input, Tabs } from '@/components/ui'
import { api, ApiError } from '@/lib/api'
import { AuthLayout, Notice } from '@/features/auth/AuthLayout'
import { portalAcceptInvite, portalInvite, portalKeys, portalLogin, portalLogout, usePortalMe, type PortalInvite } from '@/api/portal'
import { Bills, Orders, Overview, Payments, SendInvoice, Statement } from './PortalTabs'

type Tab = 'overview' | 'orders' | 'bills' | 'payments' | 'statement' | 'send'

const GOOGLE_ERRORS: Record<string, string> = {
  google_failed: 'Google sign-in did not complete. Try again.',
  google_no_email: 'Google did not share an email address.',
  google_unverified: 'That Google address is not verified.',
  google_unknown: 'No partner login uses that Google address. Ask the office to open the portal to it.',
  account_disabled: 'This login is no longer open. Ask the office.',
}

function useGoogle() {
  const [on, setOn] = useState(false)
  useEffect(() => { api<{ configured?: boolean }>('/api/auth/google/status', { quiet: true }).then((d) => setOn(!!d?.configured)).catch(() => undefined) }, [])
  return on
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
  const google = useGoogle()
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await portalLogin(email, password)
      await qc.invalidateQueries({ queryKey: portalKeys.me })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not sign in.')
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
        <Button type="submit" loading={busy}>Sign in</Button>
      </form>
      {google && <Button variant="outline" className="mt-3 w-full" onClick={() => window.location.assign('/api/auth/google/start?who=portal')}>Continue with Google</Button>}
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
  const google = useGoogle()
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
      {google && <Button variant="outline" className="mt-3 w-full" onClick={() => window.location.assign('/api/auth/google/start?who=portal')}>Or skip the password: continue with Google</Button>}
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
          {tab === 'bills' && <Bills gang={me.party_type === 'contractor'} />}
          {tab === 'payments' && <Payments />}
          {tab === 'statement' && <Statement />}
          {tab === 'send' && <SendInvoice />}
        </div>
      </div>
    </div>
  )
}
