import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Pause, Pencil, Play, Plus, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select, Stat, StatGrid } from '@/components/ui'
import { deleteRecurring, pauseRecurring, recurringKeys, resumeRecurring, saveRecurring, useRecurring, type Recurring, type RecurringStatus } from '@/api/recurring'
import { useAccounts, useMoneyHeads } from '@/api/ledger'
import { PayeeBankFields, TaxSelection } from '@/features/ledger/TaxFields'
import { bankFrom, bankPayload, bankReady, NO_BANK, NO_TAX, taxFrom, taxPayload, taxReady, type BankValue, type TaxValue } from '@/features/ledger/taxValues'
import { PAY_MODES } from '@/api/money'
import { paymentKeys } from '@/api/payments'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

const TONE: Record<RecurringStatus, 'success' | 'warning' | 'neutral'> = { Active: 'success', Paused: 'warning', Ended: 'neutral' }
/** Everything a recurring payment changes: its own list, and the requests it raises. */
const REFRESH = [recurringKeys.all, paymentKeys.all, ['approvals'], ['dashboard']]

/** 1st, 2nd, 3rd, 4th... */
const ordinal = (n: number) => `${n}${[11, 12, 13].includes(n % 100) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'}`

/**
 * Rent, internet, hire and insurance: set up once, and on its day each month a payment request is raised for approval, so
 * it is not entered by hand every month. The request is approved and paid in Payment Approvals like any other; nothing is
 * paid that nobody signed for.
 */
export default function RecurringPage() {
  const { can } = useSession()
  const q = useRecurring()
  const s = q.data?.summary
  const rows = q.data?.payments ?? []
  const edit = can('accounts.manage')
  const [form, setForm] = useState<Recurring | 'new' | null>(null)
  const [removing, setRemoving] = useState<Recurring | null>(null)
  const pause = useAction((r: Recurring) => pauseRecurring(r.id), { invalidate: REFRESH })
  const resume = useAction((r: Recurring) => resumeRecurring(r.id), { invalidate: REFRESH })
  const remove = useAction((r: Recurring) => deleteRecurring(r.id), { invalidate: REFRESH, onSuccess: () => setRemoving(null) })
  const nextOf = rows.filter((r) => r.status === 'Active' && r.next_due === s?.next_due)[0]

  const columns: TableColumn<Recurring>[] = [
    { id: 'payee', header: 'Payee', sort: (r) => r.payee.toLowerCase(), cell: (r) => <div className="min-w-40"><div className="font-medium">{r.payee}</div><div className="text-xs text-muted-foreground">{r.head}{r.project ? ` - ${r.project}` : ''}</div>{r.last_error && <div role="alert" className="mt-0.5 text-xs text-danger">Could not be raised: {r.last_error}</div>}</div> },
    { id: 'amount', header: 'Amount', align: 'right', sort: (r) => r.amount, cell: (r) => <span className="tabular font-semibold">{formatINR(r.amount)}</span> },
    { id: 'day', header: 'Falls due', hideBelow: 'md', sort: (r) => r.day_of_month, cell: (r) => <div>{ordinal(r.day_of_month)} of every month<div className="text-xs text-muted-foreground">{r.end_date ? `until ${formatDate(r.end_date)}` : 'until stopped'}</div></div> },
    { id: 'next', header: 'Next', sort: (r) => r.next_due || '9999', cell: (r) => (r.next_due ? formatDate(r.next_due) : <span className="text-muted-foreground">-</span>) },
    { id: 'last', header: 'Last request', hideBelow: 'lg', cell: (r) => (r.last_request ? <div><Link to="/money/approvals" className="font-mono text-[13px] text-primary underline-offset-4 hover:underline">{r.last_request.number}</Link><div className="text-xs text-muted-foreground">{r.last_request.status} - {r.raised_count} raised</div></div> : <span className="text-muted-foreground">none yet</span>) },
    { id: 'status', header: 'Status', cell: (r) => <Badge tone={TONE[r.status]} dot>{r.status}</Badge> },
    ...(edit ? [{
      id: 'act', header: '', align: 'right' as const, cell: (r: Recurring) => (
        <div className="flex justify-end gap-1">
          <Button size="icon-sm" variant="ghost" aria-label={`Edit ${r.payee}`} onClick={() => setForm(r)}><Pencil /></Button>
          {r.status === 'Active' && <Button size="icon-sm" variant="ghost" aria-label={`Pause ${r.payee}`} title="Pause" loading={pause.isPending && pause.variables?.id === r.id} onClick={() => pause.mutate(r)}><Pause /></Button>}
          {r.status !== 'Active' && <Button size="icon-sm" variant="ghost" aria-label={`Resume ${r.payee}`} title="Resume" loading={resume.isPending && resume.variables?.id === r.id} onClick={() => resume.mutate(r)}><Play /></Button>}
          <Button size="icon-sm" variant="ghost" aria-label={`Delete ${r.payee}`} onClick={() => setRemoving(r)}><Trash2 /></Button>
        </div>
      ),
    }] : []),
  ]
  return (
    <>
      <PageHeader eyebrow="Accounts" title="Recurring Payments" description="Rent, internet, hire and insurance: set once, and a payment request is raised for approval on its day each month."
        actions={edit ? <Button onClick={() => setForm('new')}><Plus /> Recurring payment</Button> : undefined} />
      <StatGrid>
        <Stat label="Active" value={s?.active ?? 0} sub={s?.paused ? `${s.paused} paused` : undefined} loading={q.isPending} />
        <Stat label="Every month" value={compactINR(s?.monthly)} loading={q.isPending} />
        <Stat label="Next one" value={s?.next_due ? formatDate(s.next_due) : '-'} sub={nextOf ? `${nextOf.payee}, ${formatINR(nextOf.amount)}` : undefined} loading={q.isPending} />
        <Stat label="Could not be raised" value={s?.failing ?? 0} tone={s?.failing ? 'danger' : undefined} loading={q.isPending} />
      </StatGrid>
      {pause.error && <p role="alert" className="mb-3 text-[13px] text-danger">{pause.error.message}</p>}
      {resume.error && <p role="alert" className="mb-3 text-[13px] text-danger">{resume.error.message}</p>}
      <DataTable label="Recurring payments" rows={rows} columns={columns} rowKey={(r) => r.id} loading={q.isPending}
        empty={edit ? 'Nothing recurring is set up. Add the rent, the internet, the hire - whatever is paid every month - and it is raised for approval on its day.' : 'Nothing recurring is set up.'} />
      <p className="mt-3 text-xs text-muted-foreground">Each month's request waits in <Link to="/money/approvals" className="text-primary underline underline-offset-4">Payment Approvals</Link> and is paid from there. A change here applies from the next request; requests already raised are not rewritten.</p>
      {form && <RecurringModal key={form === 'new' ? 'new' : form.id} target={form} onClose={() => setForm(null)} />}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Take ${removing?.payee ?? ''} off the list?`} tone="danger" confirmLabel="Take off" loading={remove.isPending}
        description="Nothing more is raised for it. Requests already raised stay in Payment Approvals." onConfirm={() => { if (removing) remove.mutate(removing) }} />
    </>
  )
}

function RecurringModal({ target, onClose }: { target: Recurring | 'new'; onClose: () => void }) {
  const r = target === 'new' ? null : target
  const heads = useMoneyHeads()
  const accounts = useAccounts()
  const projects = useProjects()
  const [payee, setPayee] = useState(r?.payee ?? '')
  const [head, setHead] = useState(r?.head ?? '')
  const [amount, setAmount] = useState(r?.amount ?? 0)
  const [day, setDay] = useState(r?.day_of_month ?? 1)
  const [from, setFrom] = useState(r?.start_date ?? today())
  const [until, setUntil] = useState(r?.end_date ?? '')
  const [job, setJob] = useState(r?.job_id ? String(r.job_id) : '')
  const [account, setAccount] = useState(r?.account_id ? String(r.account_id) : '')
  const [mode, setMode] = useState(r?.mode ?? '')
  const [note, setNote] = useState(r?.note ?? '')
  // The same tax selection and bank transfer details as an expense voucher: each month's request is raised with them.
  const [taxv, setTaxv] = useState<TaxValue>(r ? taxFrom(r) : NO_TAX)
  const [bankv, setBankv] = useState<BankValue>(r ? bankFrom(r) : NO_BANK)
  const bankTransfer = mode === 'Bank transfer'
  // One set up before the tax selection existed may be saved without choosing it; a new one, or one that has it, needs it complete.
  const taxOk = (r && !r.tax && !taxv.tax) || taxReady(taxv)
  const list = heads.data?.expense ?? []
  const save = useAction(
    () => saveRecurring(r?.id ?? null, { payee: payee.trim(), head: head || list[0] || '', amount, day_of_month: day, start_date: from, end_date: until, job_id: Number(job) || null, account_id: Number(account) || null, mode, note, ...(taxv.tax ? taxPayload(taxv) : {}), ...(bankTransfer ? bankPayload(bankv) : { payee_bank: '', payee_account: '', payee_ifsc: '' }) }),
    { invalidate: REFRESH, onSuccess: onClose },
  )
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={r ? `Recurring payment: ${r.payee}` : 'New recurring payment'}
      description="A payment request is raised for approval on this day every month. It is paid from Payment Approvals, like any other.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Paid to" htmlFor="rp-payee"><Input id="rp-payee" value={payee} onChange={(e) => setPayee(e.target.value)} placeholder="Sri Lakshmi Estates" autoFocus /></Field>
        <Field label="Expense head" htmlFor="rp-head"><Select id="rp-head" value={head || list[0] || ''} onChange={(e) => setHead(e.target.value)} options={list.map((h) => ({ value: h, label: h }))} /></Field>
        <div className="sm:col-span-2"><TaxSelection id="rp" value={taxv} onChange={setTaxv} amount={amount} /></div>
        <Field label="Amount each month" htmlFor="rp-amount"><NumField id="rp-amount" value={amount} onValue={setAmount} /></Field>
        <Field label="Day of the month" htmlFor="rp-day" hint="In a month with fewer days, the last day.">
          <Select id="rp-day" value={String(day)} onChange={(e) => setDay(Number(e.target.value))} options={Array.from({ length: 31 }, (_, i) => ({ value: String(i + 1), label: ordinal(i + 1) }))} />
        </Field>
        <Field label="From" htmlFor="rp-from" hint="The first request is on this day or the next one the payment falls due."><Input id="rp-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="Until" htmlFor="rp-until" hint="Leave blank to carry on until you stop it."><Input id="rp-until" type="date" value={until} min={from} onChange={(e) => setUntil(e.target.value)} /></Field>
        <Field label="Project" htmlFor="rp-job" hint="Charged to its cost. Blank: head office."><Select id="rp-job" value={job} onChange={(e) => setJob(e.target.value)} placeholder="Head office" options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Usually paid from" htmlFor="rp-account"><Select id="rp-account" value={account} onChange={(e) => setAccount(e.target.value)} placeholder="Chosen when it is paid" options={(accounts.data ?? []).map((a) => ({ value: a.id, label: `${a.name} (${a.kind})` }))} /></Field>
        <Field label="Mode" htmlFor="rp-mode"><Select id="rp-mode" value={mode} onChange={(e) => setMode(e.target.value)} placeholder="Chosen when it is paid" options={PAY_MODES.filter((m) => m !== 'Adjustment').map((m) => ({ value: m, label: m }))} /></Field>
        {bankTransfer && <div className="sm:col-span-2"><PayeeBankFields id="rp" value={bankv} onChange={setBankv} legend="Bank transfer: where the money goes each month" /></div>}
        <Field label="Note" htmlFor="rp-note"><Input id="rp-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Site office, Vizag" /></Field>
      </div>
      {payee.trim() && amount > 0 && <p className="mt-4 rounded-lg bg-muted/50 p-3 text-sm"><strong>{formatINR(amount)}</strong> to <strong>{payee.trim()}</strong> on the <strong>{ordinal(day)}</strong> of every month{until ? `, until ${formatDate(until)}` : ''}.</p>}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!payee.trim() || amount <= 0 || !taxOk || (bankTransfer && !bankReady(bankv))} onClick={() => save.mutate()}>{r ? 'Save' : 'Set it up'}</Button>
      </div>
    </Modal>
  )
}
