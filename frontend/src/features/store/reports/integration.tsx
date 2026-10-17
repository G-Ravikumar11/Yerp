import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { PackageCheck } from 'lucide-react'
import { DataTable } from '@/components/data/DataTable'
import { Button, Card, Input, Modal, Select } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'
import { storePerm } from '@/api/store'
import { recordRecovery, useLegacyStatus, usePoReceipts, useRecoveryDue } from './api'

/**
 * What the Store module shows inside other modules' screens (P5's integration hooks). Each is self-contained, so the
 * existing screen only places it: nothing here changes how those screens save or post.
 */

const n = (v: string) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })

/** Old stock screens: once the Store module is in use and the old balances are carried over, go to stock enquiry. */
export function LegacyHandover({ to = '/store/hub/enquiry' }: { to?: string }) {
  const q = useLegacyStatus()
  return q.data?.redirect ? <Navigate to={to} replace /> : null
}

/** Old goods-receipt screen: goods are received in Store > Inward now; this screen no longer books stock. */
export function StoreReceiveNotice() {
  const q = useLegacyStatus()
  if (!q.data?.legacy_receipt_blocked) return null
  return (
    <Card className="mb-4 flex flex-wrap items-center justify-between gap-3 border-primary/40 p-4 text-sm">
      <span>Goods are received in <strong>Store &gt; Inward</strong>, which books them into the store's stock. Receipts here can no longer post stock; the match against orders and bills below still works.</span>
      <Button asChild size="sm"><Link to="/store/hub/inward/grn/new"><PackageCheck /> New GRN</Link></Button>
    </Card>
  )
}

/** Purchase order: received / pending per line from the Store module, and the way to receive more. */
export function PoReceiptsButton({ poId, number }: { poId: number; number: string }) {
  const [open, setOpen] = useState(false)
  const status = useLegacyStatus()
  if (!status.data?.store_active) return null
  return (
    <>
      <button type="button" className="text-xs text-primary underline-offset-2 hover:underline" onClick={() => setOpen(true)}>Received</button>
      {open && <PoReceiptsModal poId={poId} number={number} onClose={() => setOpen(false)} />}
    </>
  )
}

function PoReceiptsModal({ poId, number, onClose }: { poId: number; number: string; onClose: () => void }) {
  const q = usePoReceipts(poId)
  const { can } = useSession()
  return (
    <Modal open size="lg" onOpenChange={(o) => !o && onClose()} title={`${number}: received and pending`} description="From goods received notes posted in Store > Inward, in each line's own unit."
      footer={<>{can(storePerm('inward', 'create')) && <Button asChild><Link to={q.data?.receive_path ?? '/store/hub/inward/grn/new'}><PackageCheck /> Receive in Store</Link></Button>}<Button variant="outline" onClick={onClose}>Close</Button></>}>
      <DataTable
        label="Receipts"
        rows={q.data?.lines ?? []}
        rowKey={(l) => l.po_line_id}
        loading={q.isPending}
        empty="Nothing received yet."
        columns={[
          { id: 'item', header: 'Line', cell: (l) => <div><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.description}</div> },
          { id: 'ord', header: 'Ordered', align: 'right', cell: (l) => `${n(l.ordered)} ${l.uom}` },
          { id: 'acc', header: 'Accepted', align: 'right', cell: (l) => `${n(l.accepted)} ${l.uom}` },
          { id: 'rej', header: 'Rejected', align: 'right', hideBelow: 'md', cell: (l) => (Number(l.rejected) ? `${n(l.rejected)} ${l.uom}` : '-') },
          { id: 'pend', header: 'Pending', align: 'right', cell: (l) => <strong>{n(l.pending)} {l.uom}</strong> },
        ]}
      />
    </Modal>
  )
}

/** Subcontractor bill: the material recovery due, read-only, with a way to note what this bill recovers. The bill's own
 * deductions are still typed on the bill - this panel never changes it. */
export function SubBillRecoveryPanel({ billId }: { billId: number }) {
  const status = useLegacyStatus()
  const q = useRecoveryDue(status.data?.store_active ? billId : 0)
  const { can } = useSession()
  const [kind, setKind] = useState('MATERIAL')
  const [amount, setAmount] = useState('')
  const save = useAction(() => recordRecovery(billId, { kind, amount, note: '' }), { invalidate: [['store', 'integration', 'sub-bill', billId]], success: 'Recovery noted.', onSuccess: () => setAmount('') })
  const d = q.data
  if (!d || Number(d.material_recoverable) + Number(d.wastage_recoverable) === 0) return null
  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold">Material recovery due (Store)</h3>
      <p className="mb-3 text-xs text-muted-foreground">{d.note}</p>
      <div className="grid gap-2 text-sm sm:grid-cols-3">
        <div>Material issued, chargeable<div className="font-semibold">{formatINR(Number(d.material_due))}</div><div className="text-xs text-muted-foreground">of {formatINR(Number(d.material_recoverable))}; {formatINR(Number(d.material_recovered))} recovered</div></div>
        <div>Wastage beyond the norms<div className="font-semibold">{formatINR(Number(d.wastage_due))}</div><div className="text-xs text-muted-foreground">of {formatINR(Number(d.wastage_recoverable))}; {formatINR(Number(d.wastage_recovered))} recovered</div></div>
        <div>Due now<div className="text-lg font-semibold">{formatINR(Number(d.total_due))}</div></div>
      </div>
      {!!d.wastage.length && (
        <ul className="mt-3 space-y-0.5 text-xs text-muted-foreground">{d.wastage.map((w, i) => <li key={i}>{w.item_code} {w.item_name}: {n(w.excess)} {w.base_uom} beyond the allowance at {formatINR(Number(w.penal_rate))} = {formatINR(Number(w.recoverable))}</li>)}</ul>
      )}
      {!!d.on_this_bill.length && <p className="mt-2 text-xs">Noted on this bill: {d.on_this_bill.map((r) => `${formatINR(Number(r.amount))} ${r.kind === 'MATERIAL' ? 'material' : 'wastage'}`).join(', ')}</p>}
      {can(storePerm('reports', 'create')) && Number(d.total_due) > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="w-44"><Select aria-label="Recovery for" value={kind} options={[{ value: 'MATERIAL', label: 'Material issued' }, { value: 'EXCESS_WASTAGE', label: 'Excess wastage' }]} onChange={(e) => setKind(e.target.value)} /></div>
          <Input aria-label="Amount recovered" className="w-36 text-right" inputMode="decimal" placeholder="0.00" value={amount} onChange={(e) => /^\d*\.?\d{0,2}$/.test(e.target.value) && setAmount(e.target.value)} />
          <Button size="sm" variant="outline" loading={save.isPending} disabled={!Number(amount)} onClick={() => save.mutate()}>Note recovery on this bill</Button>
        </div>
      )}
    </Card>
  )
}
