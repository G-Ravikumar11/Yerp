import { useMemo, useState } from 'react'
import { Download, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select, Stat, StatGrid, Tabs } from '@/components/ui'
import {
  addBook, addPdc, bankPdc, batchCancel, batchFileUrl, batchPaid, closePdc, makeBatch, payoutKeys, spoilLeaf, useBatches, useCandidates,
  useChequeBooks, useLeaves, usePdcs, type Batch, type Candidate, type ChequeBook, type Pdc,
} from '@/api/payouts'
import { PARTY_LABEL, useAccounts } from '@/api/ledger'
import { owedKeys } from '@/api/owed'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

type Tab = 'files' | 'pdc' | 'books'
const INVALIDATE = [payoutKeys.all, owedKeys.all, ['ledger'], ['money'], ['supplier-bills']]

/**
 * Money going out through the bank: payment files written in the bank's bulk-upload layout (uploaded at the bank, then
 * marked paid here, which enters each payment in the bank book), post-dated cheques given and held, and the cheque books
 * with every leaf accounted for.
 */
export default function BankPaymentsPage() {
  const [tab, setTab] = useState<Tab>('files')
  return (
    <>
      <PageHeader eyebrow="Accounts" title="Bank Payments & Cheques"
        description="Pay many bills at once with your bank's upload file, keep post-dated cheques until their day, and account for every cheque leaf." />
      <div className="mb-4">
        <Tabs label="Bank payments" value={tab} onChange={setTab} items={[
          { value: 'files', label: 'Payment files', info: 'Choose the bills, download the file in your bank\'s layout, upload it in net banking. Once the bank has paid, mark the file paid: each payment goes in the bank book.' },
          { value: 'pdc', label: 'Post-dated cheques', info: 'Cheques dated ahead - given to suppliers or held from clients. Not money until their day; then bank them and they go in the bank book.' },
          { value: 'books', label: 'Cheque books', info: 'Each book from the bank, leaf by leaf: written, given post-dated, spoilt or blank.' },
        ]} />
      </div>
      {tab === 'files' ? <Files /> : tab === 'pdc' ? <Pdcs /> : <Books />}
    </>
  )
}

function Files() {
  const { can } = useSession()
  const q = useBatches()
  const [making, setMaking] = useState(false)
  const [paying, setPaying] = useState<Batch | null>(null)
  const [open, setOpen] = useState<Batch | null>(null)
  const cancel = useAction((id: number) => batchCancel(id), { invalidate: INVALIDATE })
  const cols: TableColumn<Batch>[] = [
    { id: 'n', header: 'File', cell: (r) => <div><div className="font-mono text-xs font-medium">{r.number}</div><div className="text-xs text-muted-foreground">{formatDate(r.pay_on)}</div></div> },
    { id: 'b', header: 'From', cell: (r) => <div><div>{r.account}</div><div className="text-xs text-muted-foreground">{r.format_label}</div></div> },
    { id: 'c', header: 'Payments', align: 'right', hideBelow: 'sm', cell: (r) => r.count },
    { id: 't', header: 'Total', align: 'right', cell: (r) => <span className="font-semibold tabular-nums">{formatINR(r.total)}</span> },
    {
      id: 's', header: 'Status',
      cell: (r) => {
        const failed = r.lines.filter((l) => l.status === 'FAILED').length
        return <Badge tone={r.status === 'PAID' ? 'success' : r.status === 'CANCELLED' ? 'neutral' : failed ? 'danger' : 'warning'}>
          {r.status === 'DRAFT' ? (failed ? `${failed} could not be paid` : 'Waiting for the bank') : r.status.toLowerCase()}</Badge>
      },
    },
    {
      id: 'x', header: '', align: 'right',
      cell: (r) => (
        <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
          {r.status === 'DRAFT' && <Button size="sm" variant="outline" asChild><a href={batchFileUrl(r.id)}><Download /> File</a></Button>}
          {r.status === 'DRAFT' && can('bills.pay') && <Button size="sm" onClick={() => setPaying(r)}>Bank has paid</Button>}
          {r.status === 'DRAFT' && can('bills.pay') && <Button size="sm" variant="ghost" loading={cancel.isPending && cancel.variables === r.id} onClick={() => cancel.mutate(r.id)}>Close</Button>}
        </div>
      ),
    },
  ]
  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">Check the first file with your bank: banks sometimes set a layout of their own for a customer.</p>
        {can('bills.pay') && <Button onClick={() => setMaking(true)}><Plus /> New payment file</Button>}
      </div>
      <DataTable label="Payment files" rows={q.data?.batches ?? []} columns={cols} rowKey={(r) => r.id} loading={q.isPending} onRowClick={setOpen}
        empty="No payment files yet. Make one to pay several suppliers and contractors in one upload." />
      {making && q.data && <NewFile accounts={q.data.accounts} formats={q.data.formats} onClose={() => setMaking(false)} />}
      {paying && <PaidModal batch={paying} onClose={() => setPaying(null)} />}
      {open && (
        <Modal open onOpenChange={() => setOpen(null)} title={`${open.number} - ${open.account}`} description={open.format_label} size="lg">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="py-2">To</th><th className="py-2">Account</th><th className="py-2">Mode</th><th className="py-2 text-right">Amount</th><th className="py-2"></th></tr></thead>
            <tbody>{open.lines.map((l) => (
              <tr key={l.id} className="border-b border-border last:border-0 align-top">
                <td className="py-2">{l.party_name}<div className="text-xs text-muted-foreground">{l.doc_number}</div></td>
                <td className="py-2 font-mono text-xs">{l.account}<div>{l.ifsc}</div></td>
                <td className="py-2">{l.mode}</td>
                <td className="py-2 text-right tabular-nums">{formatINR(l.amount)}</td>
                <td className="py-2"><Badge tone={l.status === 'PAID' ? 'success' : l.status === 'FAILED' ? 'danger' : 'neutral'} title={l.error || undefined}>{l.status.toLowerCase()}</Badge>
                  {l.error && <div className="mt-1 max-w-[14rem] text-xs text-danger">{l.error}</div>}</td>
              </tr>
            ))}</tbody>
          </table>
        </Modal>
      )}
    </>
  )
}

function NewFile({ accounts, formats, onClose }: { accounts: { id: number; name: string; has_number: boolean }[]; formats: { key: string; label: string }[]; onClose: () => void }) {
  const c = useCandidates(true)
  const [account, setAccount] = useState(accounts.find((a) => a.has_number)?.id ?? 0)
  const [fmt, setFmt] = useState('csv')
  const [on, setOn] = useState(today())
  const [picked, setPicked] = useState<Record<string, number>>({})
  const key = (i: Candidate) => `${i.doc_type}-${i.doc_id}-${i.request_id}`
  const items = c.data?.items ?? []
  const chosen = items.filter((i) => picked[key(i)] !== undefined)
  const total = chosen.reduce((s, i) => s + (picked[key(i)] || 0), 0)
  const save = useAction(() => makeBatch({ account_id: account, bank_format: fmt, pay_on: on, items: chosen.map((i) => ({ ...i, amount: picked[key(i)] })) }),
    { invalidate: INVALIDATE, onSuccess: onClose })
  const toggle = (i: Candidate) => setPicked((p) => {
    const n = { ...p }
    if (n[key(i)] !== undefined) delete n[key(i)]
    else n[key(i)] = i.amount
    return n
  })
  const acc = accounts.find((a) => a.id === account)
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="New payment file" size="xl"
      description={c.data?.approval_on ? 'Payments need approval, so the file takes payments already approved and not yet paid.' : 'Bills with money still to pay. Tick the ones to pay; part-pay by changing the amount.'}
      footer={<>
        <span className="mr-auto text-sm text-muted-foreground">{chosen.length} chosen - {formatINR(total)}</span>
        <Button variant="ghost" onClick={onClose}>Not now</Button>
        <Button loading={save.isPending} disabled={!chosen.length || !account || !acc?.has_number} onClick={() => save.mutate()}>Make the file</Button>
      </>}>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Field label="Pay from" error={acc && !acc.has_number ? 'No account number on file for it - add it under Ledgers & Bank.' : undefined}>
          <Select value={account || ''} onChange={(e) => setAccount(Number(e.target.value))} placeholder="Choose the bank account" options={accounts.map((a) => ({ value: a.id, label: a.name }))} />
        </Field>
        <Field label="Bank's layout"><Select value={fmt} onChange={(e) => setFmt(e.target.value)} options={formats.map((f) => ({ value: f.key, label: f.label }))} /></Field>
        <Field label="Pay on"><Input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
      </div>
      {c.isPending ? <p className="text-sm text-muted-foreground">Loading what is waiting to be paid...</p> : items.length === 0 ? <p className="text-sm text-muted-foreground">Nothing is waiting to be paid.</p> : (
        <div className="max-h-[50vh] overflow-y-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card"><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="w-8 py-2 pl-3"></th><th className="py-2">To</th><th className="py-2">Bank details</th><th className="py-2 pr-3 text-right">Amount</th></tr></thead>
            <tbody>{items.map((i) => {
              const k = key(i)
              const off = !!i.problem || i.in_a_file
              return (
                <tr key={k} className={`border-b border-border last:border-0 ${off ? 'opacity-60' : ''}`}>
                  <td className="py-2 pl-3"><input type="checkbox" aria-label={`Pay ${i.party_name} ${i.doc_number}`} disabled={off} checked={picked[k] !== undefined} onChange={() => toggle(i)} /></td>
                  <td className="py-2"><div className="font-medium">{i.party_name}</div><div className="text-xs text-muted-foreground">{PARTY_LABEL[i.party_type] ?? i.party_type} - {i.doc_number || i.request_number || 'on account'}</div></td>
                  <td className="py-2 text-xs">{i.problem ? <span className="text-danger">{i.problem}</span> : i.in_a_file ? <span className="text-warning">already in a file</span> : <span className="font-mono">{i.account} / {i.ifsc}</span>}</td>
                  <td className="py-2 pr-3 text-right">
                    {picked[k] !== undefined && !i.request_id
                      ? <NumField aria-label="Amount" className="ml-auto w-32" value={picked[k]} onValue={(n) => setPicked((p) => ({ ...p, [k]: Math.min(n, i.amount) }))} />
                      : <span className="tabular-nums">{formatINR(i.amount)}</span>}
                  </td>
                </tr>
              )
            })}</tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}

function PaidModal({ batch, onClose }: { batch: Batch; onClose: () => void }) {
  const [on, setOn] = useState(batch.pay_on || today())
  const [ref, setRef] = useState('')
  const save = useAction(() => batchPaid(batch.id, on, ref), { invalidate: INVALIDATE, onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`${batch.number}: the bank has paid`} size="sm"
      description={`Each of the ${batch.count} payments (${formatINR(batch.total)}) goes in the bank book as paid on this day. Do this only once the bank shows them paid.`}
      footer={<><Button variant="ghost" onClick={onClose}>Not now</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Enter the payments</Button></>}>
      <div className="grid gap-3">
        <Field label="Paid on"><Input type="date" value={on} max={today()} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Bank's reference" hint="The batch or UTR the bank gave; the file number is used when blank."><Input value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
      </div>
    </Modal>
  )
}

function Pdcs() {
  const { can } = useSession()
  const q = usePdcs()
  const accounts = useAccounts()
  const [adding, setAdding] = useState(false)
  const [banking, setBanking] = useState<Pdc | null>(null)
  const [closing, setClosing] = useState<Pdc | null>(null)
  const [bankOn, setBankOn] = useState(today())
  const bank = useAction((p: Pdc) => bankPdc(p.id, bankOn, p.account_id), { invalidate: INVALIDATE, onSuccess: () => setBanking(null) })
  const close = useAction((v: { id: number; reason: string }) => closePdc(v.id, 'RETURNED', v.reason), { invalidate: INVALIDATE, onSuccess: () => setClosing(null) })
  const s = q.data?.summary
  const cols: TableColumn<Pdc>[] = [
    { id: 'd', header: 'Dated', cell: (r) => <div><div>{formatDate(r.cheque_date)}</div>{r.status === 'HELD' && r.days_to_go !== null && <div className={`text-xs ${r.due ? 'font-semibold text-danger' : 'text-muted-foreground'}`}>{r.due ? 'due now' : `in ${r.days_to_go} days`}</div>}</div> },
    { id: 'w', header: 'Cheque', cell: (r) => <div><div className="font-mono text-xs">{r.cheque_no}</div><div className="text-xs text-muted-foreground">{r.direction === 'OUT' ? `Given, on ${r.account}` : `Held${r.drawn_on ? `, ${r.drawn_on}` : ''}`}</div></div> },
    { id: 'p', header: 'Party', cell: (r) => <div><div>{r.party_name}</div><div className="text-xs text-muted-foreground">{r.doc_number || PARTY_LABEL[r.party_type] || r.party_type}</div></div> },
    { id: 'a', header: 'Amount', align: 'right', cell: (r) => <span className="font-semibold tabular-nums">{formatINR(r.amount)}</span> },
    { id: 's', header: 'Status', cell: (r) => <Badge tone={r.status === 'HELD' ? (r.due ? 'danger' : 'warning') : r.status === 'BANKED' ? 'success' : 'neutral'} title={r.closed_reason || undefined}>{r.status.toLowerCase()}</Badge> },
    {
      id: 'x', header: '', align: 'right',
      cell: (r) => r.status === 'HELD' && can('bills.pay') ? (
        <div className="flex justify-end gap-1">
          <Button size="sm" disabled={(r.days_to_go ?? 0) > 0} title={(r.days_to_go ?? 0) > 0 ? 'Not before the date on the cheque' : undefined} onClick={() => { setBankOn(today()); setBanking(r) }}>
            {r.direction === 'OUT' ? 'Presented' : 'Deposited'}</Button>
          <Button size="sm" variant="ghost" onClick={() => setClosing(r)}>Returned</Button>
        </div>
      ) : null,
    },
  ]
  return (
    <>
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Given, not yet presented" value={formatINR(s?.given ?? 0)} loading={q.isPending} />
        <Stat label="Held, not yet deposited" value={formatINR(s?.held ?? 0)} loading={q.isPending} />
        <Stat label="Due now" value={String(s?.due ?? 0)} tone={s?.due ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Within a week" value={String(s?.this_week ?? 0)} loading={q.isPending} />
      </StatGrid>
      <div className="mb-3 flex justify-end">{can('bills.pay') && <Button onClick={() => setAdding(true)}><Plus /> Post-dated cheque</Button>}</div>
      <DataTable label="Post-dated cheques" rows={q.data?.cheques ?? []} columns={cols} rowKey={(r) => r.id} loading={q.isPending}
        empty="No post-dated cheques. Add one given to a supplier or contractor, or held from a client." />
      {adding && <PdcModal accounts={(accounts.data ?? []).filter((a) => a.kind !== 'Cash')} onClose={() => setAdding(false)} />}
      <Modal open={!!banking} onOpenChange={(o) => !o && setBanking(null)} size="sm" title={`Cheque ${banking?.cheque_no ?? ''} ${banking?.direction === 'OUT' ? 'presented' : 'deposited'}`}
        description={`${formatINR(banking?.amount ?? 0)} ${banking?.direction === 'OUT' ? 'to' : 'from'} ${banking?.party_name ?? ''} goes in the bank book on this day.`}
        footer={<><Button variant="ghost" onClick={() => setBanking(null)}>Not now</Button><Button loading={bank.isPending} onClick={() => banking && bank.mutate(banking)}>Enter it</Button></>}>
        <Field label="Day it went through"><Input type="date" value={bankOn} max={today()} onChange={(e) => setBankOn(e.target.value)} /></Field>
      </Modal>
      <ConfirmDialog open={!!closing} onOpenChange={(o) => !o && setClosing(null)} title={`Cheque ${closing?.cheque_no ?? ''} returned`} confirmLabel="Mark returned" tone="danger"
        description="Given back, replaced, or bounced before it was banked. It never becomes money." reason={{ label: 'What happened', required: true }}
        loading={close.isPending} onConfirm={(reason) => { if (closing) close.mutate({ id: closing.id, reason }) }} />
    </>
  )
}

function PdcModal({ accounts, onClose }: { accounts: { id: number; name: string }[]; onClose: () => void }) {
  const [f, setF] = useState({ direction: 'OUT', cheque_no: '', cheque_date: today(), drawn_on: '', account_id: accounts[0]?.id ?? 0, party_type: 'supplier', party_name: '', amount: 0, note: '' })
  const save = useAction(() => addPdc(f), { invalidate: INVALIDATE, onSuccess: onClose })
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Post-dated cheque" size="md"
      footer={<><Button variant="ghost" onClick={onClose}>Not now</Button><Button loading={save.isPending} disabled={!f.cheque_no || !f.party_name || f.amount <= 0} onClick={() => save.mutate()}>Keep it</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Which way"><Select value={f.direction} onChange={set('direction')} options={[{ value: 'OUT', label: 'We gave it' }, { value: 'IN', label: 'We hold it' }]} /></Field>
        <Field label="Cheque no."><Input className="font-mono" value={f.cheque_no} onChange={set('cheque_no')} /></Field>
        <Field label="Date on the cheque"><Input type="date" value={f.cheque_date} onChange={set('cheque_date')} /></Field>
        <Field label="Amount"><NumField value={f.amount} onValue={(n) => setF((s) => ({ ...s, amount: n }))} /></Field>
        <Field label={f.direction === 'OUT' ? 'Drawn on (ours)' : 'To deposit in'}><Select value={f.account_id || ''} onChange={(e) => setF((s) => ({ ...s, account_id: Number(e.target.value) }))} placeholder="Choose" options={accounts.map((a) => ({ value: a.id, label: a.name }))} /></Field>
        {f.direction === 'IN' && <Field label="Their bank"><Input value={f.drawn_on} onChange={set('drawn_on')} /></Field>}
        <Field label="Party"><Select value={f.party_type} onChange={set('party_type')} options={['supplier', 'contractor', 'client', 'staff', 'other'].map((t) => ({ value: t, label: PARTY_LABEL[t] ?? t }))} /></Field>
        <Field label="Name"><Input value={f.party_name} onChange={set('party_name')} /></Field>
        <Field label="Note" className="sm:col-span-2"><Input value={f.note} onChange={set('note')} placeholder="What it is for" /></Field>
      </div>
    </Modal>
  )
}

function Books() {
  const { can } = useSession()
  const q = useChequeBooks()
  const accounts = useAccounts()
  const [adding, setAdding] = useState(false)
  const [open, setOpen] = useState<ChequeBook | null>(null)
  const cols: TableColumn<ChequeBook>[] = [
    { id: 'a', header: 'Account', cell: (r) => <div><div>{r.account}</div><div className="text-xs text-muted-foreground">from {formatDate(r.received_on)}</div></div> },
    { id: 'r', header: 'Leaves', cell: (r) => <span className="font-mono text-xs">{r.first_no} - {r.last_no}</span> },
    { id: 'b', header: 'Blank', align: 'right', cell: (r) => <span className={r.blank <= 5 ? 'font-semibold text-warning' : ''}>{r.blank} of {r.leaves}</span> },
    { id: 's', header: 'Spoilt', align: 'right', hideBelow: 'sm', cell: (r) => r.spoilt || '-' },
    { id: 'n', header: 'Next leaf', align: 'right', cell: (r) => <span className="font-mono">{r.next_leaf ?? 'none left'}</span> },
  ]
  return (
    <>
      <div className="mb-3 flex justify-end">{can('bills.pay') && <Button onClick={() => setAdding(true)}><Plus /> Cheque book</Button>}</div>
      <DataTable label="Cheque books" rows={q.data ?? []} columns={cols} rowKey={(r) => r.id} loading={q.isPending} onRowClick={setOpen}
        empty="No cheque books entered. Add each book from the bank to account for every leaf." />
      {adding && <BookModal accounts={(accounts.data ?? []).filter((a) => a.kind !== 'Cash')} onClose={() => setAdding(false)} />}
      {open && <LeavesModal book={open} onClose={() => setOpen(null)} />}
    </>
  )
}

function BookModal({ accounts, onClose }: { accounts: { id: number; name: string }[]; onClose: () => void }) {
  const [f, setF] = useState({ account_id: accounts[0]?.id ?? 0, first_no: 0, last_no: 0, received_on: today() })
  const save = useAction(() => addBook(f), { invalidate: INVALIDATE, success: 'Cheque book added', onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Cheque book" size="sm"
      footer={<><Button variant="ghost" onClick={onClose}>Not now</Button><Button loading={save.isPending} disabled={!f.account_id || f.first_no <= 0 || f.last_no < f.first_no} onClick={() => save.mutate()}>Add</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Account" className="sm:col-span-2"><Select value={f.account_id || ''} onChange={(e) => setF((s) => ({ ...s, account_id: Number(e.target.value) }))} placeholder="Choose" options={accounts.map((a) => ({ value: a.id, label: a.name }))} /></Field>
        <Field label="First leaf"><NumField value={f.first_no} onValue={(n) => setF((s) => ({ ...s, first_no: Math.round(n) }))} /></Field>
        <Field label="Last leaf"><NumField value={f.last_no} onValue={(n) => setF((s) => ({ ...s, last_no: Math.round(n) }))} /></Field>
        <Field label="Received on" className="sm:col-span-2"><Input type="date" value={f.received_on} onChange={(e) => setF((s) => ({ ...s, received_on: e.target.value }))} /></Field>
      </div>
    </Modal>
  )
}

function LeavesModal({ book, onClose }: { book: ChequeBook; onClose: () => void }) {
  const { can } = useSession()
  const q = useLeaves(book.id)
  const [spoiling, setSpoiling] = useState<number | null>(null)
  const spoil = useAction((v: { n: number; reason: string }) => spoilLeaf(book.id, v.n, v.reason), { invalidate: INVALIDATE, onSuccess: () => setSpoiling(null) })
  const tone = useMemo(() => ({ ISSUED: 'info', CLEARED: 'success', 'POST-DATED': 'warning', SPOILT: 'danger', VOID: 'danger', BLANK: 'neutral' }) as Record<string, 'info' | 'success' | 'warning' | 'danger' | 'neutral'>, [])
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`${book.account}: leaves ${book.first_no} - ${book.last_no}`} size="lg">
      <div className="max-h-[60vh] overflow-y-auto">
        <table className="w-full text-sm">
          <tbody>{(q.data ?? []).map((l) => (
            <tr key={l.number} className="border-b border-border last:border-0">
              <td className="py-1.5 font-mono text-xs">{l.number}</td>
              <td className="py-1.5"><Badge tone={tone[l.status] ?? 'neutral'}>{l.status.toLowerCase()}</Badge></td>
              <td className="py-1.5">{l.party}{l.status === 'SPOILT' && <span className="text-xs text-muted-foreground">{l.ref}</span>}</td>
              <td className="py-1.5 text-xs text-muted-foreground">{formatDate(l.date)}</td>
              <td className="py-1.5 text-right tabular-nums">{l.amount ? formatINR(l.amount) : ''}</td>
              <td className="py-1.5 text-right">{l.status === 'BLANK' && can('bills.pay') && <Button size="sm" variant="ghost" onClick={() => setSpoiling(l.number)}>Spoilt</Button>}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <ConfirmDialog open={spoiling !== null} onOpenChange={(o) => !o && setSpoiling(null)} title={`Leaf ${spoiling ?? ''} spoilt`} confirmLabel="Mark spoilt" tone="danger"
        reason={{ label: 'What happened to it', required: true }} loading={spoil.isPending} onConfirm={(reason) => { if (spoiling !== null) spoil.mutate({ n: spoiling, reason }) }} />
    </Modal>
  )
}
