import { useState } from 'react'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select, Skeleton, Stat, StatGrid, Tabs } from '@/components/ui'
import { addLoan, deleteLoan, loanKeys, previewEmi, saveInstalment, useLoan, useLoans, type Instalment, type Loan } from '@/api/loans'
import { ledgerKeys, useAccounts } from '@/api/ledger'
import { bookKeys } from '@/api/books'
import { PAY_MODES } from '@/api/money'
import { owedKeys } from '@/api/owed'
import { PayModal } from '@/features/money/PayModal'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { financialYearStart, formatDate, today } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

/** Everything a loan changes: its own list and schedule, the bank book, the party and money screens, the books. */
const REFRESH = [loanKeys.all, ledgerKeys.all, owedKeys.all, bookKeys.all, ['dashboard']]

/** The rate as it is read: 9, or 9.25. */
const rate = (n: number) => `${Math.round(n * 100) / 100}%`

/** Loans and their EMIs: what was borrowed, what is left, and the next instalment. An instalment is paid like any bill, and the books split it. */
export default function LoansPage() {
  const { can } = useSession()
  const q = useLoans()
  const s = q.data?.summary
  const [opening, setOpening] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)
  const columns: TableColumn<Loan>[] = [
    { id: 'loan', header: 'Loan', sort: (l) => l.lender.toLowerCase(), cell: (l) => <div className="min-w-44"><div className="font-medium">{l.lender}{l.name ? ` - ${l.name}` : ''}</div><div className="text-xs text-muted-foreground"><span className="font-mono">{l.number}</span> - {l.kind}{l.existing ? ' - was running before these books' : ''}</div></div> },
    { id: 'amount', header: 'Loan', align: 'right', hideBelow: 'lg', sort: (l) => l.principal, cell: (l) => <div className="tabular">{formatINR(l.principal)}<div className="text-xs text-muted-foreground">{rate(l.annual_rate)} a year</div></div> },
    { id: 'left', header: 'Still owed', align: 'right', sort: (l) => l.outstanding, cell: (l) => <div className="tabular"><span className="font-semibold">{formatINR(l.outstanding)}</span><div className="text-xs text-muted-foreground">{l.paid} of {l.instalments} paid</div></div> },
    { id: 'emi', header: 'EMI', align: 'right', hideBelow: 'md', sort: (l) => l.emi, cell: (l) => <span className="tabular">{formatINR(l.emi)}</span> },
    { id: 'next', header: 'Next instalment', sort: (l) => l.next?.due_on ?? '9999', cell: (l) => (l.next ? <div>{formatDate(l.next.due_on)} - <span className="tabular">{formatINR(l.next.total)}</span>{l.next.overdue && <Badge tone="danger" className="ml-1.5">{l.next.days_late} days late</Badge>}</div> : <span className="text-muted-foreground">-</span>) },
    { id: 'status', header: 'Status', cell: (l) => <Badge tone={l.status === 'CLOSED' ? 'neutral' : l.overdue ? 'danger' : 'success'} dot>{l.status === 'CLOSED' ? 'Repaid' : l.overdue ? 'Overdue' : 'Running'}</Badge> },
  ]
  return (
    <>
      <PageHeader eyebrow="Accounts" title="Loans & EMIs" description="What the company has borrowed, what is left, and the next instalment. Each EMI is paid like a bill; the books split it into the principal and the interest."
        actions={can('accounts.manage') ? <Button onClick={() => setAdding(true)}><Plus /> Loan</Button> : undefined} />
      <StatGrid>
        <Stat label="Still owed" value={compactINR(s?.outstanding)} sub={s ? `${s.active} running${s.closed ? `, ${s.closed} repaid` : ''}` : undefined} loading={q.isPending} />
        <Stat label="EMIs a month" value={compactINR(s?.emi_a_month)} loading={q.isPending} />
        <Stat label="Due this week" value={s?.due_week ?? 0} sub={s?.due_week ? compactINR(s.due_week_amount) : undefined} tone={s?.due_week ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Overdue" value={s?.overdue ?? 0} sub={s?.overdue ? compactINR(s.overdue_amount) : undefined} tone={s?.overdue ? 'danger' : undefined} loading={q.isPending} />
        <Stat label="Interest paid" value={compactINR(s?.interest_paid)} sub={s?.interest_to_come ? `${compactINR(s.interest_to_come)} still to come` : undefined} loading={q.isPending} />
      </StatGrid>
      <DataTable label="Loans" rows={q.data?.loans ?? []} columns={columns} rowKey={(l) => l.id} loading={q.isPending} onRowClick={(l) => setOpening(l.id)}
        empty={can('accounts.manage') ? 'No loan is entered. Add a bank loan, a vehicle or equipment loan, or one from a director, and its instalments are worked out.' : 'No loan is entered.'} />
      {opening !== null && <LoanModal id={opening} onClose={() => setOpening(null)} />}
      {adding && <NewLoanModal onClose={() => setAdding(false)} onAdded={(l) => { setAdding(false); setOpening(l.id) }} />}
    </>
  )
}

function LoanModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { can } = useSession()
  const q = useLoan(id)
  const l = q.data
  const [paying, setPaying] = useState<Instalment | null>(null)
  const [fixing, setFixing] = useState<Instalment | null>(null)
  const [removing, setRemoving] = useState(false)
  const remove = useAction(() => deleteLoan(id), { invalidate: REFRESH, onSuccess: onClose })
  const columns: TableColumn<Instalment>[] = [
    { id: 'n', header: 'No.', cell: (i) => <span className="tabular">{i.seq}</span> },
    { id: 'due', header: 'Due', cell: (i) => <div>{formatDate(i.due_on)}{i.overdue && <Badge tone="danger" className="ml-1.5">{i.days_late} days late</Badge>}</div> },
    { id: 'p', header: 'Principal', align: 'right', cell: (i) => <span className="tabular">{formatINR(i.principal)}</span> },
    { id: 'i', header: 'Interest', align: 'right', cell: (i) => <span className="tabular">{formatINR(i.interest)}</span> },
    { id: 't', header: 'EMI', align: 'right', cell: (i) => <span className="tabular font-semibold">{formatINR(i.total)}</span> },
    { id: 's', header: 'Paid', cell: (i) => (i.status === 'PAID' ? <Badge tone="success" dot>{formatDate(i.paid_on)}</Badge> : <span className="text-muted-foreground">not yet</span>) },
    {
      id: 'act', header: '', align: 'right', cell: (i) => (i.status === 'PAID' ? null : (
        <div className="flex justify-end gap-1">
          {can('bills.pay') && <Button size="sm" variant="outline" onClick={() => setPaying(i)}>Pay</Button>}
          {can('accounts.manage') && <Button size="icon-sm" variant="ghost" aria-label={`Change instalment ${i.seq}`} onClick={() => setFixing(i)}><Pencil /></Button>}
        </div>
      )),
    },
  ]
  return (
    <>
      <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title={l ? `${l.number}: ${l.lender}${l.name ? ` - ${l.name}` : ''}` : 'Loan'}
        description={l ? `${formatINR(l.principal)} at ${rate(l.annual_rate)} a year, ${l.instalments} instalments of about ${formatINR(l.emi)}. Its ledger in the books is "${l.ledger}".` : undefined}>
        {!l ? <Skeleton className="h-64 w-full" /> : (
          <>
            <StatGrid className="xl:grid-cols-4">
              <Stat label="Still owed" value={formatINR(l.outstanding)} sub={`${formatINR(l.repaid)} repaid`} />
              <Stat label="Instalments paid" value={`${l.paid} of ${l.instalments}`} />
              <Stat label="Interest paid" value={formatINR(l.interest_paid)} />
              <Stat label="Interest to come" value={formatINR(l.interest_to_come)} />
            </StatGrid>
            {l.existing && <p className="mb-3 rounded-lg bg-muted/50 p-2.5 text-[13px]">Already running when these books began: entered as it stood on {formatDate(l.taken_on)}, so no money received is recorded.</p>}
            {!l.received && <p role="alert" className="mb-3 rounded-lg border border-warning/40 bg-warning-soft p-2.5 text-[13px]">The money received on this loan has been voided, so it is not counted as owed. Enter it again, or take the loan away.</p>}
            <DataTable label="Instalments" rows={l.schedule ?? []} columns={columns} rowKey={(i) => i.id} />
            {l.note && <p className="mt-3 text-[13px] text-muted-foreground">{l.note}</p>}
            <div className="mt-4 flex items-center justify-between gap-2 border-t border-border pt-4">
              {can('accounts.manage') ? <Button variant="ghost" onClick={() => setRemoving(true)}><Trash2 /> Take this loan away</Button> : <span />}
              <Button variant="outline" onClick={onClose}>Close</Button>
            </div>
            {remove.error && <p role="alert" className="mt-2 text-[13px] text-danger">{remove.error.message}</p>}
          </>
        )}
      </Modal>
      {paying && <PayModal docType="loan_instalment" docId={paying.id} title={paying.number} verb="Pay" open onOpenChange={(o) => !o && setPaying(null)} invalidate={REFRESH} />}
      {fixing && l && <InstalmentModal loan={l.id} instalment={fixing} onClose={() => setFixing(null)} />}
      <ConfirmDialog open={removing} onOpenChange={setRemoving} title={`Take ${l?.number ?? 'this loan'} away?`} tone="danger" confirmLabel="Take it away" loading={remove.isPending}
        description="Only possible while nothing is paid on it and its money received is voided. The schedule goes with it." onConfirm={() => remove.mutate()} />
    </>
  )
}

/** Put an instalment right before it is paid: the bank's own split, or the day it moved to. */
function InstalmentModal({ loan, instalment: i, onClose }: { loan: number; instalment: Instalment; onClose: () => void }) {
  const [due, setDue] = useState(i.due_on)
  const [principal, setPrincipal] = useState(i.principal)
  const [interest, setInterest] = useState(i.interest)
  const save = useAction(() => saveInstalment(loan, i.id, { due_on: due, principal, interest }), { invalidate: REFRESH, onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Change ${i.number}`} description="Where the bank charged otherwise than the schedule, put it right before the payment is entered. The payment is the whole of it.">
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Due on" htmlFor="in-due"><Input id="in-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
        <Field label="Principal" htmlFor="in-p"><NumField id="in-p" value={principal} onValue={setPrincipal} /></Field>
        <Field label="Interest" htmlFor="in-i"><NumField id="in-i" value={interest} onValue={setInterest} /></Field>
      </div>
      <p className="mt-3 rounded-lg bg-muted/50 p-2.5 text-sm">The EMI is <strong>{formatINR(principal + interest)}</strong>.</p>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!due || principal + interest <= 0} onClick={() => save.mutate()}>Save</Button>
      </div>
    </Modal>
  )
}

function NewLoanModal({ onClose, onAdded }: { onClose: () => void; onAdded: (l: Loan) => void }) {
  const accounts = useAccounts()
  const [kind, setKind] = useState<'new' | 'existing'>('new')
  const [lender, setLender] = useState('')
  const [name, setName] = useState('')
  const [secured, setSecured] = useState('secured')
  const [principal, setPrincipal] = useState(0)
  const [pct, setPct] = useState(0)
  const [months, setMonths] = useState(12)
  const [taken, setTaken] = useState(today())
  const [first, setFirst] = useState('')
  const [emi, setEmi] = useState(0)
  const [account, setAccount] = useState('')
  const [mode, setMode] = useState('Bank transfer')
  const [ref, setRef] = useState('')
  const [note, setNote] = useState('')
  const only = accounts.data?.length === 1 ? String(accounts.data[0].id) : ''
  const existing = kind === 'existing'
  const preview = previewEmi(principal, pct, months)
  const save = useAction(
    () => addLoan({ lender: lender.trim(), name: name.trim(), kind: secured, principal, annual_rate: pct, months, first_due: first, emi, existing, taken_on: taken, account_id: existing ? null : Number(account || only) || null, mode, reference: ref, note }),
    { invalidate: REFRESH, onSuccess: (r) => onAdded(r.loan) },
  )
  const ready = lender.trim() && principal > 0 && months > 0 && first && taken && (existing || account || only)
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title="New loan" description="Enter the terms once and the instalments are worked out. Each EMI is then paid like a bill, and the books split it into principal and interest.">
      <div className="mb-4 max-w-md"><Tabs label="Kind of entry" value={kind} onChange={(v) => { setKind(v); setTaken(v === 'new' ? today() : financialYearStart()) }} items={[{ value: 'new', label: 'Money just received' }, { value: 'existing', label: 'Already running' }]} /></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Borrowed from" htmlFor="ln-lender"><Input id="ln-lender" value={lender} onChange={(e) => setLender(e.target.value)} placeholder="HDFC Bank" autoFocus /></Field>
        <Field label="What it is for" htmlFor="ln-name"><Input id="ln-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Excavator, working capital" /></Field>
        <Field label="Secured or not" htmlFor="ln-kind"><Select id="ln-kind" value={secured} onChange={(e) => setSecured(e.target.value)} options={[{ value: 'secured', label: 'Secured (against an asset)' }, { value: 'unsecured', label: 'Unsecured' }]} /></Field>
        <Field label={existing ? 'Principal still owed' : 'Loan amount'} htmlFor="ln-principal" hint={existing ? 'What was left of it on the day below.' : undefined}><NumField id="ln-principal" value={principal} onValue={setPrincipal} /></Field>
        <Field label="Interest, % a year" htmlFor="ln-rate" hint="Reducing balance."><NumField id="ln-rate" value={pct} onValue={setPct} /></Field>
        <Field label={existing ? 'Instalments left' : 'Number of monthly instalments'} htmlFor="ln-months"><NumField id="ln-months" value={months} onValue={(n) => setMonths(Math.round(n))} /></Field>
        <Field label={existing ? 'Balance as on' : 'Money received on'} htmlFor="ln-taken"><Input id="ln-taken" type="date" value={taken} max={today()} onChange={(e) => setTaken(e.target.value)} /></Field>
        <Field label="First instalment on" htmlFor="ln-first" hint="The same day falls due every month."><Input id="ln-first" type="date" value={first} min={taken} onChange={(e) => setFirst(e.target.value)} /></Field>
        <Field label="The bank's own EMI" htmlFor="ln-emi" hint="Optional. Leave blank to work it out."><NumField id="ln-emi" value={emi} onValue={setEmi} /></Field>
        {!existing && (
          <>
            <Field label="Paid into" htmlFor="ln-account"><Select id="ln-account" value={account || only} onChange={(e) => setAccount(e.target.value)} placeholder="Choose the account" options={(accounts.data ?? []).map((a) => ({ value: a.id, label: `${a.name} (${a.kind})` }))} /></Field>
            <Field label="Mode" htmlFor="ln-mode"><Select id="ln-mode" value={mode} onChange={(e) => setMode(e.target.value)} options={PAY_MODES.filter((m) => m !== 'Adjustment').map((m) => ({ value: m, label: m }))} /></Field>
            <Field label="Reference" htmlFor="ln-ref" className="sm:col-span-2"><Input id="ln-ref" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="UTR of the disbursal" /></Field>
          </>
        )}
        <Field label="Note" htmlFor="ln-note" className="sm:col-span-2"><Input id="ln-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Sanction letter no., security given..." /></Field>
      </div>
      {preview && !emi && <p className="mt-4 rounded-lg bg-muted/50 p-3 text-sm">About <strong>{formatINR(Math.round(preview.emi))}</strong> a month for {months} months; about <strong>{formatINR(Math.round(preview.interest))}</strong> of interest in all.</p>}
      {existing && <p className="mt-3 text-xs text-muted-foreground">No money received is recorded for a loan that was already running; the books carry what was left of it as an opening balance.</p>}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!ready} onClick={() => save.mutate()}>{existing ? 'Enter the loan' : 'Enter the loan and the money received'}</Button>
      </div>
    </Modal>
  )
}
