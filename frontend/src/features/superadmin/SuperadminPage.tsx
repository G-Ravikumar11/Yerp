import { useEffect, useMemo, useState } from 'react'
import { Button, Field, Input, Modal, Stat, StatGrid } from '@/components/ui'
import { formatINR } from '@/lib/utils'
import { formatDate } from '@/lib/format'
import { useAction } from '@/lib/mutate'
import { adjustWallet, changePassword, deleteClient, impersonate, saKeys, saLogout, savePrice, toggleClient, useClientOverview, useGateways, useInsights, useLoginLogs, useLoginStats, usePlatformStats, usePricing, useRevenue, useSaClient, useSaClients, useSaMe, useTrends, useWallets, type PriceRow, type SaClient, type WalletRow } from '@/api/superadmin'
import { appUrl } from '@/lib/paths'

const card = 'rounded-xl border border-border bg-card p-5'
const th = 'px-2 py-2 text-left text-xs font-semibold uppercase text-muted-foreground'

function Section({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-semibold">{title}</h2>{aside}</div>
      {children}
    </section>
  )
}

/** The platform operator's own screen: every company on the platform, their usage, wallets, prices and sign-ins. */
export default function SuperadminPage() {
  const me = useSaMe()
  const [passwordOpen, setPasswordOpen] = useState(false)
  useEffect(() => {
    document.title = 'Super Admin - Y ERP'
    if (!me.isLoading && !me.data) window.location.assign(appUrl('superadmin/login'))
  }, [me.isLoading, me.data])
  const out = useAction(saLogout, { success: false, onSuccess: () => window.location.assign(appUrl('superadmin/login')) })
  if (!me.data) return null
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-10 border-b border-border bg-card">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-lg bg-primary font-bold text-primary-foreground">A</span><h1 className="text-lg font-bold">Y ERP <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">Super Admin</span></h1></div>
          <div className="flex items-center gap-2 text-sm"><span className="hidden text-muted-foreground sm:inline">{me.data.username}</span><Button size="sm" variant="outline" onClick={() => setPasswordOpen(true)}>Change password</Button><Button size="sm" variant="outline" loading={out.isPending} onClick={() => out.mutate()}>Sign out</Button></div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 pb-16 pt-6">
        <Overview />
        <Billing />
        <Trends />
        <Logins />
        <Clients />
      </main>
      <PasswordModal open={passwordOpen} onClose={() => setPasswordOpen(false)} />
    </div>
  )
}

function Overview() {
  const i = useInsights().data
  const p = usePlatformStats().data
  return (
    <>
      <StatGrid>
        <Stat label="Total clients" value={i?.total_clients ?? 0} />
        <Stat label="Active clients" value={i?.active_clients ?? 0} tone="success" />
        <Stat label="Total invoices" value={i?.total_invoices ?? 0} />
        <Stat label="Outstanding" value={formatINR(i?.total_outstanding)} tone="danger" />
      </StatGrid>
      <Section title="Platform usage" aside={<span className="text-xs text-muted-foreground">Across every tenant</span>}>
        <StatGrid>
          <Stat label="Employees" value={p?.hr.employees ?? 0} sub={`${p?.hr.departments ?? 0} departments`} />
          <Stat label="Payslips issued" value={p?.hr.payslips ?? 0} sub={`Payroll paid ${formatINR(p?.hr.payroll_paid)}`} />
          <Stat label="Open roles" value={p?.recruitment.open_jobs ?? 0} sub={`${p?.recruitment.applications ?? 0} applications`} />
          <Stat label="Active (30d)" value={p?.tenants.active_last_30_days ?? 0} sub={`of ${p?.tenants.total ?? 0} tenants`} />
        </StatGrid>
      </Section>
    </>
  )
}

function Billing() {
  const r = useRevenue().data
  const g = useGateways().data
  const live = (g?.providers ?? []).filter((x) => x.enabled).map((x) => x.key)
  const top = r?.by_action[0]
  const sym = r?.symbol ?? ''
  return (
    <Section title="Billing & wallets" aside={<span className={live.length ? 'text-xs text-success' : 'text-xs text-warning'}>{live.length ? `Gateways live: ${live.join(', ')}` : 'No payment gateway configured - add keys to accept top-ups'}</span>}>
      <StatGrid>
        <Stat label="Topped up" value={sym + (r?.total_topped_up ?? 0).toLocaleString()} sub="all time" tone="success" />
        <Stat label="Consumed" value={sym + (r?.total_consumed ?? 0).toLocaleString()} sub="billed usage" />
        <Stat label="Unused credit" value={sym + (r?.outstanding_liability ?? 0).toLocaleString()} sub="owed to tenants" tone="warning" />
        <Stat label="Top action" value={top?.action_key ?? '-'} sub={top?.revenue ? sym + top.revenue.toFixed(2) : ''} />
      </StatGrid>
      <div className="mt-5 grid gap-5 lg:grid-cols-2"><Pricing /><Wallets /></div>
    </Section>
  )
}

function PriceLine({ row }: { row: PriceRow }) {
  const [price, setPrice] = useState(String(row.unit_price))
  const [free, setFree] = useState(String(row.free_allowance))
  const save = useAction(() => savePrice(row.id, parseFloat(price) || 0, parseInt(free) || 0), { invalidate: [saKeys.all] })
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border py-2">
      <div className="min-w-32 flex-1"><p className="text-sm font-medium">{row.label}</p><p className="text-xs text-muted-foreground">{row.module} · {row.action_key}</p></div>
      <Input aria-label={`Price for ${row.label}`} className="h-8 w-20" type="number" step="0.01" min="0" value={price} onChange={(e) => setPrice(e.target.value)} />
      <Input aria-label={`Free units for ${row.label}`} className="h-8 w-16" type="number" min="0" value={free} onChange={(e) => setFree(e.target.value)} />
      <Button size="sm" variant="outline" loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
    </div>
  )
}

function Pricing() {
  const rows = usePricing().data ?? []
  return (
    <div className={card}>
      <h3 className="font-semibold">What each action costs</h3>
      <p className="mb-3 text-xs text-muted-foreground">Applies to every tenant. The free allowance resets each calendar month. Price, then free units a month.</p>
      <div className="max-h-96 overflow-y-auto">{rows.map((r) => <PriceLine key={r.id} row={r} />)}</div>
    </div>
  )
}

function Wallets() {
  const rows = useWallets().data ?? []
  const [adjusting, setAdjusting] = useState<WalletRow | null>(null)
  return (
    <div className={card}>
      <h3 className="font-semibold">Tenant wallets</h3>
      <p className="mb-3 text-xs text-muted-foreground">Lowest balance first. Adjustments appear on the tenant statement.</p>
      <div className="max-h-96 overflow-y-auto">
        {rows.length === 0 && <p className="text-sm text-muted-foreground">No tenants yet.</p>}
        {rows.map((w) => (
          <div key={w.client_id} className="flex flex-wrap items-center gap-2 border-b border-border py-2">
            <div className="min-w-32 flex-1"><p className="text-sm font-medium">{w.company_name}</p><p className="text-xs text-muted-foreground">spent {w.lifetime_spent.toFixed(2)}</p></div>
            <strong className={w.is_low ? 'text-warning' : 'text-success'}>{w.balance.toFixed(2)}</strong>
            <Button size="sm" variant="outline" onClick={() => setAdjusting(w)}>Adjust</Button>
          </div>
        ))}
      </div>
      <AdjustModal wallet={adjusting} onClose={() => setAdjusting(null)} />
    </div>
  )
}

function AdjustModal({ wallet, onClose }: { wallet: WalletRow | null; onClose: () => void }) {
  const [amount, setAmount] = useState('10')
  const [reason, setReason] = useState('Manual credit')
  const go = useAction(() => adjustWallet(wallet!.client_id, parseFloat(amount), reason.trim()), { invalidate: [saKeys.all], success: (r) => `New balance: ${r.balance}`, onSuccess: onClose })
  const valid = !!parseFloat(amount) && reason.trim() !== ''
  return (
    <Modal open={!!wallet} onOpenChange={(o) => !o && onClose()} title={`Adjust ${wallet?.company_name ?? ''} wallet`} description="Positive to credit, negative to debit.">
      <div className="grid gap-4">
        <Field label="Amount" htmlFor="wa-amount"><Input id="wa-amount" type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label="Reason" htmlFor="wa-reason" hint="The tenant sees this on their statement."><Input id="wa-reason" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="flex justify-end gap-2"><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={go.isPending} disabled={!valid} onClick={() => go.mutate()}>Save</Button></div>
      </div>
    </Modal>
  )
}

function Bars({ label, values, months, money }: { label: string; values: number[]; months: string[]; money?: boolean }) {
  const max = Math.max(1, ...values)
  return (
    <div className={card}>
      <h3 className="mb-4 text-sm font-semibold text-muted-foreground">{label}</h3>
      <div className="flex h-36 items-end gap-2">
        {values.map((v, i) => (
          <div key={i} className="flex min-w-0 flex-1 flex-col items-center gap-1">
            <span className="text-[11px] font-semibold text-muted-foreground">{money ? formatINR(v) : v}</span>
            <div className="flex h-24 w-full items-end overflow-hidden rounded bg-muted"><div className="w-full rounded bg-primary" style={{ height: `${Math.max(2, Math.round((v / max) * 100))}%` }} /></div>
            <span className="w-full truncate text-center text-[11px] text-muted-foreground">{(months[i] ?? '').slice(5)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Trends() {
  const t = useTrends().data
  return (
    <Section title="6-month trends" aside={<span className="text-sm text-muted-foreground">Total revenue, all time: <strong className="text-foreground">{formatINR(t?.total_revenue)}</strong></span>}>
      {t && <div className="grid gap-5 md:grid-cols-2"><Bars label="Revenue (paid)" values={t.revenue} months={t.months} money /><Bars label="Active logins" values={t.active_users} months={t.months} /></div>}
    </Section>
  )
}

function Logins() {
  const s = useLoginStats().data
  const logs = useLoginLogs().data ?? []
  const [search, setSearch] = useState('')
  const shown = useMemo(() => logs.filter((l) => !search || `${l.email} ${l.ip_address ?? ''}`.toLowerCase().includes(search.toLowerCase())), [logs, search])
  return (
    <Section title="Login activity" aside={<Input aria-label="Search logs" className="h-9 w-56" placeholder="Search logs..." value={search} onChange={(e) => setSearch(e.target.value)} />}>
      <StatGrid>
        <Stat label="Today" value={s?.today_logins ?? 0} />
        <Stat label="This week" value={s?.week_logins ?? 0} tone="success" />
        <Stat label="Failed logins" value={s?.failed_logins ?? 0} tone="warning" />
        <Stat label="Never logged in" value={s?.clients_never_logged_in ?? 0} tone="danger" />
      </StatGrid>
      <div className="mt-4 overflow-x-auto rounded-xl border border-border bg-card">
        <table aria-label="Login activity" className="w-full text-sm">
          <thead className="border-b border-border"><tr>{['Email', 'Type', 'Method', 'IP address', 'Status', 'When'].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
          <tbody className="divide-y divide-border">
            {shown.length === 0 && <tr><td colSpan={6} className="px-2 py-6 text-center text-muted-foreground">No login activity yet</td></tr>}
            {shown.map((l, i) => <tr key={i}><td className="px-2 py-2 font-medium">{l.email}</td><td className="px-2 py-2 text-muted-foreground">{l.user_type}</td><td className="px-2 py-2">{l.login_type === 'google' ? 'Google' : 'Password'}</td><td className="px-2 py-2 font-mono text-xs text-muted-foreground">{l.ip_address || '-'}</td><td className={`px-2 py-2 font-semibold ${l.status === 'success' ? 'text-success' : l.status === 'failed' ? 'text-danger' : 'text-warning'}`}>{l.status}</td><td className="px-2 py-2 text-xs text-muted-foreground">{l.created_at}</td></tr>)}
          </tbody>
        </table>
      </div>
    </Section>
  )
}

function Clients() {
  const clients = useSaClients().data ?? []
  const [search, setSearch] = useState('')
  const [viewing, setViewing] = useState(0)
  const shown = useMemo(() => clients.filter((c) => !search || `${c.company_name} ${c.email} ${c.contact_name}`.toLowerCase().includes(search.toLowerCase())), [clients, search])
  const toggle = useAction((id: number) => toggleClient(id), { invalidate: [saKeys.all], success: false })
  const remove = useAction((id: number) => deleteClient(id), { invalidate: [saKeys.all] })
  const login = useAction((id: number) => impersonate(id), { success: false, onSuccess: () => window.location.assign(appUrl()) })
  const askLogin = (c: SaClient) => window.confirm(`Log in as ${c.company_name || c.email} to help them? You are signed in as that client until you sign out.`) && login.mutate(c.id)
  const askDelete = (c: SaClient) => window.confirm(`Delete ${c.company_name || c.email} and all their data? This cannot be undone.`) && remove.mutate(c.id)
  return (
    <Section title="All clients" aside={<Input aria-label="Search clients" className="h-9 w-56" placeholder="Search clients..." value={search} onChange={(e) => setSearch(e.target.value)} />}>
      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <table aria-label="Clients" className="w-full text-sm">
          <thead className="border-b border-border"><tr>{['Client', 'Status', 'Onboarding', 'Invoices', 'Outstanding', 'Joined', 'Actions'].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
          <tbody className="divide-y divide-border">
            {shown.length === 0 && <tr><td colSpan={7} className="px-2 py-8 text-center text-muted-foreground">No clients yet</td></tr>}
            {shown.map((c) => (
              <tr key={c.id}>
                <td className="px-2 py-2"><p className="font-medium">{c.company_name || c.contact_name || 'Unnamed'}</p><p className="text-xs text-muted-foreground">{c.email}</p></td>
                <td className="px-2 py-2">{c.is_active ? 'Active' : 'Disabled'}</td>
                <td className="px-2 py-2">{c.is_onboarded ? 'Complete' : 'Pending'}</td>
                <td className="px-2 py-2">{c.invoice_count ?? 0}</td>
                <td className="px-2 py-2">{formatINR(c.outstanding)}</td>
                <td className="px-2 py-2 text-xs text-muted-foreground">{formatDate((c.created_at || '').slice(0, 10))}<br />Login #{c.login_count || 0}</td>
                <td className="whitespace-nowrap px-2 py-2">
                  <Button size="sm" variant="outline" onClick={() => setViewing(c.id)}>View</Button>{' '}
                  <Button size="sm" variant="outline" onClick={() => askLogin(c)}>Login as</Button>{' '}
                  <Button size="sm" variant="outline" onClick={() => toggle.mutate(c.id)}>{c.is_active ? 'Disable' : 'Enable'}</Button>{' '}
                  <Button size="sm" variant="outline" className="text-danger" onClick={() => askDelete(c)}>Delete</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ClientModal id={viewing} onClose={() => setViewing(0)} />
    </Section>
  )
}

function ClientModal({ id, onClose }: { id: number; onClose: () => void }) {
  const c = useSaClient(id).data
  const o = useClientOverview(id).data
  const Group = ({ title, pairs }: { title: string; pairs: [string, React.ReactNode][] }) => (
    <div className="min-w-44 flex-1 rounded-xl border border-border p-3"><p className="mb-2 text-xs font-bold uppercase text-muted-foreground">{title}</p>{pairs.map(([k, v]) => <div key={k} className="flex justify-between gap-3 py-0.5 text-sm"><span className="text-muted-foreground">{k}</span><strong>{v}</strong></div>)}</div>
  )
  return (
    <Modal open={id > 0} onOpenChange={(open) => !open && onClose()} size="lg" title={c?.company_name || c?.contact_name || 'Client'}>
      {c && (
        <div className="grid gap-5">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            {([['Email', c.email], ['Phone', c.phone_number], ['Address', c.address], ['Tax ID', c.abn], ['Industry', c.industry], ['Joined', c.created_at], ['Status', c.is_active ? 'Active' : 'Disabled'], ['Onboarded', c.is_onboarded ? 'Yes' : 'No']] as [string, string | undefined][]).map(([k, v]) => <div key={k}><dt className="text-xs uppercase text-muted-foreground">{k}</dt><dd>{v || '-'}</dd></div>)}
          </dl>
          {o && (
            <div className="flex flex-wrap gap-3">
              <Group title="Invoicing" pairs={[['Invoices', o.invoicing.invoices], ['Collected', formatINR(o.invoicing.collected)], ['Outstanding', formatINR(o.invoicing.outstanding)], ['Overdue', o.invoicing.overdue_count]]} />
              <Group title="People" pairs={[['Employees', o.hr.employees], ['Active', o.hr.active_employees], ['Departments', o.hr.departments], ['Pending leave', o.hr.pending_leave]]} />
              <Group title="Recruitment" pairs={[['Jobs', o.recruitment.jobs], ['Open', o.recruitment.open_jobs], ['Applications', o.recruitment.applications], ['Interviews', o.recruitment.interviews]]} />
            </div>
          )}
          {o && <div className="flex flex-wrap gap-2 text-sm"><a className="text-primary underline" href={o.portals.employee} target="_blank" rel="noopener noreferrer">Staff sign-in</a><a className="text-primary underline" href={o.portals.job_board} target="_blank" rel="noopener noreferrer">Public job board</a></div>}
          <div>
            <h3 className="mb-2 text-sm font-semibold text-muted-foreground">Invoices</h3>
            <table aria-label="Client invoices" className="w-full text-sm"><thead><tr>{['Number', 'Status', 'Amount', 'Date'].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody>{(c.invoices ?? []).length === 0 ? <tr><td colSpan={4} className="py-4 text-center text-muted-foreground">No invoices yet</td></tr> : c.invoices!.map((v) => <tr key={v.number}><td className="px-2 py-1">{v.number}</td><td className="px-2 py-1">{v.status}</td><td className="px-2 py-1">{formatINR(v.due)}</td><td className="px-2 py-1">{v.date ? formatDate(v.date) : ''}</td></tr>)}</tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
  )
}

function PasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [pwd, setPwd] = useState('')
  const go = useAction(() => changePassword(pwd), { success: 'Password updated.', onSuccess: () => { setPwd(''); onClose() } })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Change password">
      <div className="grid gap-4">
        <Field label="New password" htmlFor="pwd-new" hint={pwd.length > 0 && pwd.length < 6 ? 'At least 6 characters.' : undefined}><Input id="pwd-new" type="password" autoComplete="new-password" value={pwd} onChange={(e) => setPwd(e.target.value)} placeholder="At least 6 characters" /></Field>
        <div className="flex justify-end gap-2"><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={go.isPending} disabled={pwd.length < 6} onClick={() => go.mutate()}>Save</Button></div>
      </div>
    </Modal>
  )
}
