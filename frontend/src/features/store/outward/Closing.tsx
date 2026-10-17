import { useState } from 'react'
import { Badge, Button, Field, Input, Modal, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storePerm, storePost, storePut } from '@/api/store'
import { money, num, outwardKeys, useOutwardSettings, useRecoveries, type OutwardSettings, type Recovery2, type Returnable } from './api'

/** Close what is still out on an issue line other than by getting it back: charge the holder for it, or ask for it to be written off. */
export function CloseReturnableModal({ row, mode, onClose }: { row: Returnable; mode: 'convert' | 'writeoff'; onClose: () => void }) {
  const settings = useOutwardSettings()
  const [f, setF] = useState({ qty: String(Number(row.qty_outstanding)), rate: '', handling: '', reason: '' })
  const save = useAction(() => storePost<{ message: string }>('outward', `/returnables/${row.issue_line_id}/${mode}`, mode === 'convert' ? { qty: f.qty, rate: f.rate, handling_pct: f.handling, reason: f.reason } : { qty: f.qty, reason: f.reason }),
    { invalidate: [[...outwardKeys.all]], success: (r) => r.message, onSuccess: onClose })
  const ok = Number(f.qty) > 0 && f.reason.trim() && (mode === 'writeoff' || Number(f.rate) > 0)
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={mode === 'convert' ? `Charge ${row.holder_name || 'the holder'} for ${row.item_name}` : `Ask for ${row.item_name} to be written off`}
      description={mode === 'convert' ? `${num(row.qty_outstanding)} is still out. A charge becomes a recovery to be taken from their bill.` : `${num(row.qty_outstanding)} is still out. This only raises the request; the write-off itself is posted under Control.`}>
      <form onSubmit={(e) => { e.preventDefault(); if (ok) save.mutate() }} className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Quantity" htmlFor="cl-qty"><Input id="cl-qty" inputMode="decimal" className="text-right" value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} /></Field>
          {mode === 'convert' && <Field label="Rate to recover" htmlFor="cl-rate"><Input id="cl-rate" inputMode="decimal" className="text-right" value={f.rate} onChange={(e) => setF({ ...f, rate: e.target.value })} /></Field>}
          {mode === 'convert' && <Field label="Handling %" htmlFor="cl-hand" hint={`Usually ${num(settings.data?.subcon_handling_pct ?? '0')}%`}><Input id="cl-hand" inputMode="decimal" className="text-right" placeholder="Usual" value={f.handling} onChange={(e) => setF({ ...f, handling: e.target.value })} /></Field>}
        </div>
        <Field label="Why" htmlFor="cl-why"><Input id="cl-why" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} maxLength={200} autoFocus /></Field>
        <div className="flex justify-end gap-2 border-t border-border pt-4"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={save.isPending} disabled={!ok}>{mode === 'convert' ? 'Charge it' : 'Request write-off'}</Button></div>
      </form>
    </Modal>
  )
}

/** What the store has charged to subcontractors and holders to be recovered from them, and how the rate was set. */
export function RecoveriesPage() {
  const [status, setStatus] = useState('OPEN')
  const q = useRecoveries(status)
  const columns: TableColumn<Recovery2>[] = [
    { id: 'who', header: 'Charged to', cell: (r) => <div><div className="font-medium">{r.holder_name || '-'}</div><div className="text-xs text-muted-foreground">{r.holder_type.toLowerCase()} - {r.issue_number}</div></div> },
    { id: 'item', header: 'Item', cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'qty', header: 'Charged', align: 'right', width: '8rem', cell: (r) => <span>{num(r.qty)}{Number(r.qty_returned) > 0 && <span className="text-xs text-muted-foreground"> ({num(r.qty_returned)} back)</span>}</span> },
    { id: 'basis', header: 'Rate', width: '14rem', hideBelow: 'md', cell: (r) => <span>{money(r.recovery_rate)} <span className="text-xs text-muted-foreground">{r.basis === 'CONTRACT_RATE' ? 'contract rate' : r.basis === 'CONVERSION' ? 'converted returnable' : 'average cost'}{Number(r.handling_pct) > 0 && ` + ${num(r.handling_pct)}% handling`}</span></span> },
    { id: 'amt', header: 'To recover', align: 'right', width: '9rem', sort: (r) => Number(r.amount), cell: (r) => money(r.amount) },
    { id: 'st', header: '', width: '8rem', cell: (r) => <Badge tone={r.status === 'OPEN' ? 'warning' : 'neutral'} dot>{r.source === 'CONVERSION' ? 'Converted' : r.status === 'OPEN' ? 'Chargeable' : 'Cancelled'}</Badge> },
  ]
  return (
    <div>
      <Field label="Show" htmlFor="rc2-st" className="mb-4 w-44"><Select id="rc2-st" value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: 'OPEN', label: 'To recover' }, { value: 'CANCELLED', label: 'Cancelled' }, { value: '', label: 'All' }]} /></Field>
      {q.data && <p className="mb-3 text-sm text-muted-foreground" role="status">Total to recover: <span className="font-semibold text-foreground">{money(q.data.total_amount)}</span></p>}
      {q.isError ? <p role="alert" className="text-sm text-danger">Could not load the recoveries.</p> : <DataTable label="Recoveries" rows={q.data?.items ?? []} loading={q.isPending} columns={columns} rowKey={(r) => r.id} empty="Nothing is charged to be recovered." />}
    </div>
  )
}

/** The company's outward defaults: the handling percentage on what is recovered from subcontractors, and how the rate is usually set. */
export function SettingsPage() {
  const { can } = useSession()
  const q = useOutwardSettings()
  const [f, setF] = useState<OutwardSettings | null>(null)
  const v = f ?? q.data
  const save = useAction(() => storePut<OutwardSettings>('outward', '/settings', v), { invalidate: [[...outwardKeys.all]], success: 'Settings saved', onSuccess: () => setF(null) })
  const can2 = can(storePerm('outward', 'approve'))
  if (!v) return <p className="text-sm text-muted-foreground">Loading...</p>
  return (
    <form className="grid max-w-xl gap-4" onSubmit={(e) => { e.preventDefault(); if (can2) save.mutate() }}>
      <p className="text-sm text-muted-foreground">These are what a chargeable line on a subcontractor issue starts with. Each line can still choose its own.</p>
      <Field label="Usual recovery rate" htmlFor="st-basis"><Select id="st-basis" disabled={!can2} value={v.default_recovery_basis} onChange={(e) => setF({ ...v, default_recovery_basis: e.target.value as OutwardSettings['default_recovery_basis'] })} options={[{ value: 'AVERAGE_COST', label: 'The average cost the stock left at' }, { value: 'CONTRACT_RATE', label: 'The contract rate' }]} /></Field>
      <Field label="Handling %" htmlFor="st-hand" hint="Added to the rate when material is recovered from a subcontractor."><Input id="st-hand" inputMode="decimal" disabled={!can2} className="w-32 text-right" value={v.subcon_handling_pct} onChange={(e) => setF({ ...v, subcon_handling_pct: e.target.value })} /></Field>
      {can2 ? <div><Button type="submit" loading={save.isPending} disabled={!f}>Save</Button></div> : <p className="text-xs text-muted-foreground">Changing them needs the right to approve outward documents.</p>}
    </form>
  )
}
