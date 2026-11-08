import { useMemo, useState } from 'react'
import { FileText, Plus, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select, Tabs } from '@/components/ui'
import {
  approveJournal, cancelDebitNote, cancelJournal, debitNotePdf, journalKeys, journalPdf, raiseDebitNote, raiseJournal, rejectJournal,
  useDebitNotes, useJournals, type DebitNote, type Journal, type JournalLine, type LineKind, type OpenReturn,
} from '@/api/journals'
import { PARTY_LABEL, useAccounts, useMoneyHeads } from '@/api/ledger'
import { useSupplierBills } from '@/api/bills'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

type Tab = 'journals' | 'debit'
const TONE = { PENDING: 'warning', APPROVED: 'success', REJECTED: 'danger', CANCELLED: 'neutral', ISSUED: 'success' } as const
const INVALIDATE = [journalKeys.all, ['ledger'], ['money'], ['supplier-bills'], ['approvals'], ['projects']]

/**
 * The two entries the books need that move no money. A journal voucher moves an amount between ledgers - a balance
 * written off, a cost moved from one site to another, a TDS correction - and counts only once the Master approves it.
 * A debit note to a supplier takes back part of what we owe them: goods sent back (from a store purchase return),
 * a rate above the order, short supply. Both go to Tally with the rest of the books.
 */
export default function AdjustmentsPage() {
  const [tab, setTab] = useState<Tab>('journals')
  const [job, setJob] = useState('')
  const projects = useProjects()
  const sites = useMemo(() => (projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) })), [projects.data])
  return (
    <>
      <PageHeader
        eyebrow="Accounts"
        title="Journals & Debit Notes"
        description="Adjustments between ledgers, approved by the Master, and debit notes that take back part of a supplier's bill. Both go to Tally."
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs label="Adjustments" value={tab} onChange={setTab} items={[
          { value: 'journals', label: 'Journal vouchers', info: 'A balanced entry between ledgers, a project on each line. Nothing changes in the ledgers, project costs or Tally until the Master approves it.' },
          { value: 'debit', label: 'Supplier debit notes', info: 'Takes back part of what we owe a supplier - off the bill it names, or their account. Raise one from a purchase return posted in the store, or by hand.' },
        ]} />
        <div className="w-72"><Select aria-label="Project" value={job} onChange={(e) => setJob(e.target.value)} placeholder="All projects" options={sites} /></div>
      </div>
      {tab === 'journals' ? <Journals job={Number(job) || 0} /> : <DebitNotes job={Number(job) || 0} />}
    </>
  )
}

function Journals({ job }: { job: number }) {
  const { can } = useSession()
  const q = useJournals(job)
  const [making, setMaking] = useState(false)
  const [rejecting, setRejecting] = useState<Journal | null>(null)
  const [cancelling, setCancelling] = useState<Journal | null>(null)
  const [open, setOpen] = useState<Journal | null>(null)
  const approve = useAction((id: number) => approveJournal(id), { invalidate: INVALIDATE, success: (j) => `${j.number} approved` })
  const reject = useAction((v: { id: number; note: string }) => rejectJournal(v.id, v.note), { invalidate: INVALIDATE, success: (j) => `${j.number} sent back`, onSuccess: () => setRejecting(null) })
  const cancel = useAction((v: { id: number; reason: string }) => cancelJournal(v.id, v.reason), { invalidate: INVALIDATE, success: (j) => `${j.number} cancelled`, onSuccess: () => setCancelling(null) })
  const master = !!q.data?.can_approve

  const cols: TableColumn<Journal>[] = [
    { id: 'n', header: 'Voucher', cell: (r) => <div><div className="font-mono text-xs font-medium">{r.number}</div><div className="text-xs text-muted-foreground">{formatDate(r.voucher_date)}</div></div> },
    { id: 'w', header: 'Narration', cell: (r) => <div className="max-w-md"><div className="truncate">{r.narration}</div><div className="truncate text-xs text-muted-foreground">{r.lines.map((l) => l.label).join(' / ')}</div></div> },
    { id: 'a', header: 'Amount', align: 'right', cell: (r) => <span className="font-semibold tabular-nums">{formatINR(r.total)}</span> },
    { id: 'b', header: 'Raised by', hideBelow: 'md', cell: (r) => r.raised_by_name || '-' },
    { id: 's', header: 'Status', cell: (r) => <Badge tone={TONE[r.status]} title={r.decision_note || undefined}>{r.status === 'PENDING' ? 'Waiting for the Master' : r.status.toLowerCase()}</Badge> },
    {
      id: 'x', header: '', align: 'right',
      cell: (r) => (
        <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
          {master && r.status === 'PENDING' && <Button size="sm" loading={approve.isPending && approve.variables === r.id} onClick={() => approve.mutate(r.id)}>Approve</Button>}
          {master && r.status === 'PENDING' && <Button size="sm" variant="outline" onClick={() => setRejecting(r)}>Send back</Button>}
          {r.status !== 'CANCELLED' && r.status !== 'REJECTED' && (r.status === 'PENDING' ? can('accounts.manage') : master) &&
            <Button size="sm" variant="ghost" onClick={() => setCancelling(r)}>Cancel</Button>}
          <Button size="icon-sm" variant="ghost" asChild title="Voucher PDF"><a href={journalPdf(r.id)} target="_blank" rel="noreferrer"><FileText /></a></Button>
        </div>
      ),
    },
  ]
  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{master ? 'You approve every journal before it counts.' : 'Each journal waits for the Master to approve it before it counts.'}</p>
        {can('accounts.manage') && <Button onClick={() => setMaking(true)}><Plus /> New journal</Button>}
      </div>
      <DataTable label="Journal vouchers" rows={q.data?.journals ?? []} columns={cols} rowKey={(r) => r.id} loading={q.isPending} onRowClick={setOpen}
        empty="No journal vouchers yet. Raise one to write off a balance, move a cost between sites or correct an entry." />
      {making && <JournalModal ledgers={q.data?.ledgers ?? []} defaultJob={job} onClose={() => setMaking(false)} />}
      {open && (
        <Modal open onOpenChange={() => setOpen(null)} title={`${open.number} - ${formatDate(open.voucher_date)}`} description={open.narration} size="lg">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="py-2">Account</th><th className="py-2 text-right">Debit</th><th className="py-2 text-right">Credit</th></tr></thead>
            <tbody>{open.lines.map((l, i) => (
              <tr key={i} className="border-b border-border last:border-0">
                <td className="py-2">{l.label}{l.note && <div className="text-xs text-muted-foreground">{l.note}</div>}</td>
                <td className="py-2 text-right tabular-nums">{l.debit ? formatINR(l.debit) : ''}</td>
                <td className="py-2 text-right tabular-nums">{l.credit ? formatINR(l.credit) : ''}</td>
              </tr>
            ))}</tbody>
          </table>
          <p className="mt-3 text-xs text-muted-foreground">
            Raised by {open.raised_by_name || '-'} on {formatDate(open.raised_at)}
            {open.decided_by_name && `; ${open.status.toLowerCase()} by ${open.decided_by_name} on ${formatDate(open.decided_at)}`}
            {open.decision_note && ` - ${open.decision_note}`}
          </p>
        </Modal>
      )}
      <ConfirmDialog open={!!rejecting} onOpenChange={(o) => !o && setRejecting(null)} title={`Send ${rejecting?.number ?? ''} back`} confirmLabel="Send back" tone="danger"
        reason={{ label: 'Why', required: true }} loading={reject.isPending} onConfirm={(note) => { if (rejecting) reject.mutate({ id: rejecting.id, note }) }} />
      <ConfirmDialog open={!!cancelling} onOpenChange={(o) => !o && setCancelling(null)} title={`Cancel ${cancelling?.number ?? ''}`} confirmLabel="Cancel the journal" tone="danger"
        description={cancelling?.status === 'APPROVED' ? 'It stops counting in the ledgers and project costs from now.' : undefined}
        reason={{ label: 'Why', required: true }} loading={cancel.isPending} onConfirm={(reason) => { if (cancelling) cancel.mutate({ id: cancelling.id, reason }) }} />
    </>
  )
}

const blank = (kind: LineKind, job: number): JournalLine => ({ kind, party_type: 'supplier', party_name: '', head: '', account_id: null, ledger_key: '', job_id: job || null, debit: 0, credit: 0, note: '' })

function JournalModal({ ledgers, defaultJob, onClose }: { ledgers: { key: string; label: string }[]; defaultJob: number; onClose: () => void }) {
  const [on, setOn] = useState(today())
  const [narration, setNarration] = useState('')
  const [lines, setLines] = useState<JournalLine[]>([blank('party', defaultJob), blank('head', defaultJob)])
  const heads = useMoneyHeads()
  const accounts = useAccounts()
  const projects = useProjects()
  const sites = (projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))
  const headOptions = [...(heads.data?.expense ?? []), ...(heads.data?.income ?? [])].map((h) => ({ value: h, label: h }))
  const dr = lines.reduce((s, l) => s + (l.debit || 0), 0)
  const cr = lines.reduce((s, l) => s + (l.credit || 0), 0)
  const off = Math.round((dr - cr) * 100) / 100
  const save = useAction(() => raiseJournal({ voucher_date: on, narration, lines }), { invalidate: INVALIDATE, success: (j) => `${j.number} raised; it waits for the Master`, onSuccess: onClose })
  const set = (i: number, patch: Partial<JournalLine>) => setLines((ls) => ls.map((l, n) => (n === i ? { ...l, ...patch } : l)))

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="New journal voucher" size="xl"
      description="Debits on one side, credits on the other, equal to the paisa. Put the project on each line it concerns."
      footer={<>
        <span className={`mr-auto text-sm tabular-nums ${off ? 'text-danger' : 'text-muted-foreground'}`}>Debit {formatINR(dr)} / Credit {formatINR(cr)}{off ? ` - out by ${formatINR(Math.abs(off))}` : ''}</span>
        <Button variant="ghost" onClick={onClose}>Not now</Button>
        <Button loading={save.isPending} disabled={!!off || dr <= 0 || narration.trim().length < 3} onClick={() => save.mutate()}>Send to the Master</Button>
      </>}>
      <div className="mb-4 grid gap-3 sm:grid-cols-[10rem_1fr]">
        <Field label="Date"><Input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Narration"><Input value={narration} onChange={(e) => setNarration(e.target.value)} placeholder="What it is for - this goes in the books" /></Field>
      </div>
      <div className="space-y-2">
        {lines.map((l, i) => (
          <div key={i} className="grid items-end gap-2 rounded-lg border border-border p-2 md:grid-cols-[8rem_1fr_12rem_8rem_8rem_auto]">
            <Field label="Line"><Select aria-label="Line kind" value={l.kind} onChange={(e) => set(i, { kind: e.target.value as LineKind })}
              options={[{ value: 'party', label: 'Party' }, { value: 'head', label: 'Expense / income' }, { value: 'account', label: 'Bank / cash' }, { value: 'ledger', label: 'Books ledger' }]} /></Field>
            {l.kind === 'party' ? (
              <div className="grid grid-cols-[8rem_1fr] gap-2">
                <Field label="Type"><Select aria-label="Party type" value={l.party_type} onChange={(e) => set(i, { party_type: e.target.value })}
                  options={['supplier', 'contractor', 'client', 'staff', 'other'].map((t) => ({ value: t, label: PARTY_LABEL[t] ?? t }))} /></Field>
                <Field label="Name"><Input aria-label="Party name" value={l.party_name} onChange={(e) => set(i, { party_name: e.target.value })} /></Field>
              </div>
            ) : l.kind === 'head' ? (
              <Field label="Head"><Select aria-label="Head" value={l.head} onChange={(e) => set(i, { head: e.target.value })} placeholder="Choose a head" options={headOptions} /></Field>
            ) : l.kind === 'account' ? (
              <Field label="Account"><Select aria-label="Account" value={l.account_id ?? ''} onChange={(e) => set(i, { account_id: Number(e.target.value) || null })} placeholder="Choose an account"
                options={(accounts.data ?? []).map((a) => ({ value: a.id, label: a.name }))} /></Field>
            ) : (
              <Field label="Ledger"><Select aria-label="Ledger" value={l.ledger_key} onChange={(e) => set(i, { ledger_key: e.target.value })} placeholder="Choose a ledger"
                options={ledgers.map((x) => ({ value: x.key, label: x.label }))} /></Field>
            )}
            <Field label="Project"><Select aria-label="Project" value={l.job_id ?? ''} onChange={(e) => set(i, { job_id: Number(e.target.value) || null })} placeholder="Head office" options={sites} /></Field>
            <Field label="Debit"><NumField aria-label="Debit" value={l.debit} onValue={(n) => set(i, { debit: n, credit: n ? 0 : l.credit })} /></Field>
            <Field label="Credit"><NumField aria-label="Credit" value={l.credit} onValue={(n) => set(i, { credit: n, debit: n ? 0 : l.debit })} /></Field>
            <Button size="icon-sm" variant="ghost" aria-label="Remove line" disabled={lines.length <= 2} onClick={() => setLines((ls) => ls.filter((_, n) => n !== i))}><Trash2 /></Button>
          </div>
        ))}
      </div>
      <Button className="mt-3" variant="outline" size="sm" onClick={() => setLines((ls) => [...ls, blank('head', defaultJob)])}><Plus /> Add a line</Button>
    </Modal>
  )
}

function DebitNotes({ job }: { job: number }) {
  const { can } = useSession()
  const q = useDebitNotes(job)
  const [making, setMaking] = useState<OpenReturn | 'manual' | null>(null)
  const [cancelling, setCancelling] = useState<DebitNote | null>(null)
  const cancel = useAction((v: { id: number; reason: string }) => cancelDebitNote(v.id, v.reason), { invalidate: INVALIDATE, success: (n) => `${n.number} cancelled`, onSuccess: () => setCancelling(null) })
  const returns = q.data?.returns ?? []

  const cols: TableColumn<DebitNote>[] = [
    { id: 'n', header: 'Debit note', cell: (r) => <div><div className="font-mono text-xs font-medium">{r.number}</div><div className="text-xs text-muted-foreground">{formatDate(r.note_date)}</div></div> },
    { id: 's', header: 'Supplier', cell: (r) => <div><div className="font-medium">{r.supplier_name}</div><div className="text-xs text-muted-foreground">{r.bill_number ? `Against ${r.bill_number}` : 'On their account'}</div></div> },
    { id: 'w', header: 'Why', hideBelow: 'md', cell: (r) => <div className="max-w-xs truncate">{r.reason}</div> },
    { id: 'p', header: 'Project', hideBelow: 'lg', cell: (r) => r.project || '-' },
    { id: 'a', header: 'Amount', align: 'right', cell: (r) => <div className="tabular-nums"><div className="font-semibold">{formatINR(r.total)}</div>{r.tax > 0 && <div className="text-xs text-muted-foreground">GST {formatINR(r.tax)}</div>}</div> },
    { id: 'st', header: 'Status', cell: (r) => <Badge tone={TONE[r.status]} title={r.cancel_reason || undefined}>{r.status.toLowerCase()}</Badge> },
    {
      id: 'x', header: '', align: 'right',
      cell: (r) => (
        <div className="flex justify-end gap-1">
          {r.status === 'ISSUED' && can('accounts.manage') && <Button size="sm" variant="ghost" onClick={() => setCancelling(r)}>Cancel</Button>}
          <Button size="icon-sm" variant="ghost" asChild title="Debit note PDF"><a href={debitNotePdf(r.id)} target="_blank" rel="noreferrer"><FileText /></a></Button>
        </div>
      ),
    },
  ]
  return (
    <>
      {returns.length > 0 && (
        <div className="mb-5 rounded-xl border border-warning/40 bg-warning-soft/40 p-3">
          <h2 className="mb-2 text-sm font-semibold">Goods sent back with no debit note yet</h2>
          <ul className="space-y-1.5">
            {returns.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span><span className="font-mono text-xs">{r.number}</span> - {r.supplier_name}, {formatDate(r.date)}: <span className="font-medium">{formatINR(r.total)}</span>{r.reason && <span className="text-muted-foreground"> ({r.reason})</span>}</span>
                {can('accounts.manage') && <Button size="sm" variant="outline" onClick={() => setMaking(r)}>Raise debit note</Button>}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">An issued debit note comes off the bill's balance in Money to Pay and the supplier's ledger at once.</p>
        {can('accounts.manage') && <Button onClick={() => setMaking('manual')}><Plus /> New debit note</Button>}
      </div>
      <DataTable label="Supplier debit notes" rows={q.data?.notes ?? []} columns={cols} rowKey={(r) => r.id} loading={q.isPending}
        empty="No debit notes yet. Raise one when goods go back, a rate is charged above the order, or supply is short." />
      {making && <DebitNoteModal from={making === 'manual' ? null : making} defaultJob={job} onClose={() => setMaking(null)} />}
      <ConfirmDialog open={!!cancelling} onOpenChange={(o) => !o && setCancelling(null)} title={`Cancel ${cancelling?.number ?? ''}`} confirmLabel="Cancel the debit note" tone="danger"
        description="What it took off the bill and the supplier's account goes back on." reason={{ label: 'Why', required: true }} loading={cancel.isPending}
        onConfirm={(reason) => { if (cancelling) cancel.mutate({ id: cancelling.id, reason }) }} />
    </>
  )
}

function DebitNoteModal({ from, defaultJob, onClose }: { from: OpenReturn | null; defaultJob: number; onClose: () => void }) {
  const [on, setOn] = useState(today())
  const [supplier, setSupplier] = useState(from?.supplier_name ?? '')
  const [billId, setBillId] = useState<number | null>(from?.bills.length === 1 ? from.bills[0].id : null)
  const [reason, setReason] = useState(from ? `Goods returned - ${from.number}${from.reason ? ': ' + from.reason : ''}` : '')
  const [taxable, setTaxable] = useState(from?.taxable ?? 0)
  const [tax, setTax] = useState(from?.tax ?? 0)
  const bills = useSupplierBills()
  const billOptions = from
    ? from.bills.map((b) => ({ value: b.id, label: `${b.number} - ${formatINR(b.total)}` }))
    : (bills.data ?? []).filter((b) => (!supplier || b.vendor_name.toLowerCase() === supplier.trim().toLowerCase()) && !['Draft', 'Cancelled', 'Rejected', 'Paid'].includes(b.status))
      .map((b) => ({ value: b.id, label: `${b.number} - ${b.vendor_name} - ${formatINR(b.total - (b.amount_paid || 0))} to pay` }))
  const save = useAction(() => raiseDebitNote({ note_date: on, supplier_name: supplier, bill_id: billId, purchase_return_id: from?.id ?? null, job_id: from?.job_id ?? (defaultJob || null), reason, taxable, tax }),
    { invalidate: INVALIDATE, success: (n) => `${n.number} issued to ${n.supplier_name}`, onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={from ? `Debit note for ${from.number}` : 'New debit note'} size="md"
      description="Choose the bill it comes off; with no bill it comes off the supplier's account."
      footer={<>
        <Button variant="ghost" onClick={onClose}>Not now</Button>
        <Button loading={save.isPending} disabled={taxable <= 0 || reason.trim().length < 3 || (!supplier.trim() && !billId)} onClick={() => save.mutate()}>Issue {formatINR(taxable + tax)}</Button>
      </>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Date"><Input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Supplier"><Input value={supplier} disabled={!!from} onChange={(e) => setSupplier(e.target.value)} placeholder="As on their bills" /></Field>
        <Field label="Against bill" className="sm:col-span-2"><Select aria-label="Bill" value={billId ?? ''} onChange={(e) => setBillId(Number(e.target.value) || null)} placeholder="No bill - their account" options={billOptions} /></Field>
        <Field label="Why" className="sm:col-span-2"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Goods returned, rate above order, short supply..." /></Field>
        <Field label="Amount before GST"><NumField value={taxable} onValue={setTaxable} /></Field>
        <Field label="GST"><NumField value={tax} onValue={setTax} /></Field>
      </div>
    </Modal>
  )
}
