import { useState } from 'react'
import { Plus } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, Field, Input, Modal, NumField, Select, Stat, StatGrid } from '@/components/ui'
import { createAccount, ledgerKeys, useAccounts, useBook, type Book } from '@/api/ledger'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

type Row = Book['rows'][number]

function AccountModal({ open, onClose, onAdded }: { open: boolean; onClose: () => void; onAdded: (id: number) => void }) {
  const [f, setF] = useState({ name: '', kind: 'Bank', bank_name: '', account_no: '', ifsc: '', opening_balance: 0, opening_date: today() })
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  const save = useAction(() => createAccount(f), { invalidate: [ledgerKeys.all, ['money']], success: (r) => `${r.name} added`, onSuccess: (r) => { onClose(); onAdded(r.id) } })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Bank account or cash box" description="The bank account payments go through, and a cash box for each site that keeps petty cash.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor="ac-name"><Input id="ac-name" value={f.name} onChange={set('name')} placeholder="SBI current - Hyderabad" autoFocus /></Field>
        <Field label="Kind" htmlFor="ac-kind"><Select id="ac-kind" value={f.kind} onChange={set('kind')} options={['Bank', 'Cash'].map((k) => ({ value: k, label: k }))} /></Field>
        <Field label="Bank" htmlFor="ac-bank"><Input id="ac-bank" value={f.bank_name} onChange={set('bank_name')} /></Field>
        <Field label="Account no." htmlFor="ac-no"><Input id="ac-no" value={f.account_no} onChange={set('account_no')} /></Field>
        <Field label="IFSC" htmlFor="ac-ifsc"><Input id="ac-ifsc" className="font-mono uppercase" value={f.ifsc} onChange={set('ifsc')} /></Field>
        <Field label="Opening balance" htmlFor="ac-open"><NumField id="ac-open" value={f.opening_balance} onValue={(n) => setF((s) => ({ ...s, opening_balance: n }))} /></Field>
        <Field label="Opening date" htmlFor="ac-date"><Input id="ac-date" type="date" value={f.opening_date} onChange={set('opening_date')} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!f.name.trim()} onClick={() => save.mutate()}>Add the account</Button>
      </div>
    </Modal>
  )
}

/** The bank book: every rupee through an account, with the running balance. */
export function BankTab() {
  const accounts = useAccounts()
  const [picked, setPicked] = useState(0)
  const [adding, setAdding] = useState(false)
  const chosen = picked || accounts.data?.[0]?.id || 0
  const book = useBook(chosen)
  const b = book.data

  const columns: TableColumn<Row>[] = [
    { id: 'date', header: 'Date', cell: (r) => formatDate(r.date) },
    { id: 'no', header: 'No.', cell: (r) => <span className="font-mono text-[13px]">{r.number}</span> },
    { id: 'party', header: 'Party', cell: (r) => r.party },
    { id: 'against', header: 'Against', hideBelow: 'md', cell: (r) => r.against },
    { id: 'mode', header: 'Mode', hideBelow: 'lg', cell: (r) => `${r.mode} ${r.reference}`.trim() },
    { id: 'in', header: 'In', align: 'right', cell: (r) => (r.received ? formatINR(r.received) : '') },
    { id: 'out', header: 'Out', align: 'right', cell: (r) => (r.paid ? formatINR(r.paid) : '') },
    { id: 'bal', header: 'Balance', align: 'right', cell: (r) => <span className="font-semibold">{formatINR(r.balance)}</span> },
  ]

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        {!!accounts.data?.length && <div className="w-72"><Select aria-label="Account" value={chosen} onChange={(e) => setPicked(Number(e.target.value))} options={accounts.data.map((a) => ({ value: a.id, label: `${a.name} (${a.kind})` }))} /></div>}
        <Button variant="outline" size="sm" onClick={() => setAdding(true)}><Plus /> Bank account or cash box</Button>
      </div>
      {accounts.data && accounts.data.length === 0 ? (
        <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No accounts yet. Add the bank account payments go through, and a cash box for each site that keeps petty cash.</p>
      ) : (
        <>
          <StatGrid className="xl:grid-cols-4">
            <Stat label="Opening" value={compactINR(b?.opening)} loading={book.isPending} />
            <Stat label="Received" value={compactINR(b?.received)} loading={book.isPending} />
            <Stat label="Paid out" value={compactINR(b?.paid)} loading={book.isPending} />
            <Stat label="Balance" value={compactINR(b?.closing)} loading={book.isPending} />
          </StatGrid>
          <DataTable label="Bank book" rows={b?.rows ?? []} columns={columns} rowKey={(r) => r.number} loading={book.isPending} empty="Nothing through this account yet." />
        </>
      )}
      <AccountModal open={adding} onClose={() => setAdding(false)} onAdded={setPicked} />
    </>
  )
}
