import { useState } from 'react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { grnKeys, startReceipt, useOpenOrders, type Grn } from '@/api/grn'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

/** Take a delivery against an approved order: who sent it, the challan, the vehicle. The quantities are checked next. */
export function ReceiveModal({ open, onClose, onStarted }: { open: boolean; onClose: () => void; onStarted: (g: Grn) => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Receive a delivery" description="Against an approved purchase order with material still to come.">
      {open && <Form onClose={onClose} onStarted={onStarted} />}
    </Modal>
  )
}

function Form({ onClose, onStarted }: { onClose: () => void; onStarted: (g: Grn) => void }) {
  const orders = useOpenOrders()
  const [order, setOrder] = useState('')
  const [f, setF] = useState({ received_on: today(), challan_number: '', invoice_number: '', vehicle_number: '', store_location: '', inspected_by: '' })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const list = orders.data ?? []
  const pick = order || (list[0] ? String(list[0].id) : '')
  const start = useAction(() => startReceipt({ purchase_order_id: Number(pick), ...f }), { invalidate: [grnKeys.all], success: (g) => `${g.number} opened - check the quantities against the lorry`, onSuccess: onStarted })
  return (
    <div>
      {list.length === 0 && !orders.isPending ? <p className="rounded-lg bg-muted/50 p-3 text-sm">No approved orders with material still to come. Approve a purchase order first.</p> : (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Order" htmlFor="gr-order" className="sm:col-span-2"><Select id="gr-order" value={pick} onChange={(e) => setOrder(e.target.value)} options={list.map((o) => ({ value: o.id, label: `${o.number} - ${o.supplier_name} (${formatINR(o.pending_value)} to come)` }))} /></Field>
          <Field label="Received on" htmlFor="gr-on"><Input id="gr-on" type="date" value={f.received_on} onChange={set('received_on')} /></Field>
          <Field label="Challan no." htmlFor="gr-challan"><Input id="gr-challan" value={f.challan_number} onChange={set('challan_number')} /></Field>
          <Field label="Supplier's invoice no." htmlFor="gr-inv"><Input id="gr-inv" value={f.invoice_number} onChange={set('invoice_number')} /></Field>
          <Field label="Vehicle" htmlFor="gr-veh"><Input id="gr-veh" value={f.vehicle_number} onChange={set('vehicle_number')} /></Field>
          <Field label="Into the store" htmlFor="gr-store"><Input id="gr-store" value={f.store_location} onChange={set('store_location')} placeholder="Main store" /></Field>
          <Field label="Inspected by" htmlFor="gr-insp"><Input id="gr-insp" value={f.inspected_by} onChange={set('inspected_by')} /></Field>
        </div>
      )}
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {start.error && <p role="alert" className="mr-auto text-[13px] text-danger">{start.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={start.isPending} disabled={!pick} onClick={() => start.mutate()}>Open the receipt</Button>
      </div>
    </div>
  )
}
