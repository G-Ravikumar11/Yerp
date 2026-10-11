import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { sendCost, staffKeys, useMyJobs, type MyCost } from '@/api/staff'
import { usePurchaseOrders } from '@/api/purchaseOrders'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const CATEGORIES = [
  { value: 'materials', label: 'Materials' },
  { value: 'subcontractor', label: 'Subcontractor' },
  { value: 'plant_hire', label: 'Plant hire' },
  { value: 'fuel', label: 'Fuel and travel' },
  { value: 'general', label: 'General' },
]

export function CostFormModal({ cost, open, onClose }: { cost: MyCost | null; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={cost ? `Fix ${cost.number}` : 'Raise a cost'} description={cost?.rejection_reason ? `Sent back: ${cost.rejection_reason}` : 'It goes up the line for approval.'}>
      {open && <Form key={cost?.id ?? 'new'} cost={cost} onClose={onClose} />}
    </Modal>
  )
}

function Form({ cost, onClose }: { cost: MyCost | null; onClose: () => void }) {
  const jobs = useMyJobs()
  const orders = usePurchaseOrders(true)
  const [vendor, setVendor] = useState(cost?.vendor_name ?? '')
  const [amount, setAmount] = useState(cost?.amount ?? 0)
  const [tax, setTax] = useState(cost?.tax_amount ?? 0)
  const [date, setDate] = useState(cost?.issue_date || today())
  const [reference, setReference] = useState(cost?.reference ?? '')
  const [category, setCategory] = useState(cost?.category || 'materials')
  const [job, setJob] = useState(cost?.job_id ? String(cost.job_id) : '')
  const [order, setOrder] = useState(cost?.purchase_order_id ? String(cost.purchase_order_id) : '')
  const [notes, setNotes] = useState(cost?.notes ?? '')
  const agreed = (orders.data ?? []).filter((o) => o.status === 'Approved' || o.approval_status === 'approved' || o.id === cost?.purchase_order_id)
  const save = useAction(
    () => sendCost(cost?.id ?? null, { vendor_name: vendor.trim(), amount, tax_amount: tax, issue_date: date, reference: reference.trim(), category, notes: notes.trim(), job_id: job ? Number(job) : null, purchase_order_id: order ? Number(order) : null }),
    { invalidate: [staffKeys.all, ['approvals']], success: (r) => r.message || 'Sent for approval', onSuccess: onClose },
  )
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Owed to" htmlFor="co-vendor" className="sm:col-span-2"><Input id="co-vendor" value={vendor} onChange={(e) => setVendor(e.target.value)} placeholder="Who is to be paid" autoFocus /></Field>
        <Field label="Amount (before tax)" htmlFor="co-amount"><NumField id="co-amount" value={amount} onValue={setAmount} /></Field>
        <Field label="GST" htmlFor="co-tax"><NumField id="co-tax" value={tax} onValue={setTax} /></Field>
        <Field label="Date on the bill" htmlFor="co-date"><Input id="co-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Bill or receipt number" htmlFor="co-ref"><Input id="co-ref" value={reference} onChange={(e) => setReference(e.target.value)} /></Field>
        <Field label="Category" htmlFor="co-cat"><Select id="co-cat" value={category} onChange={(e) => setCategory(e.target.value)} options={CATEGORIES} /></Field>
        <Field label="Job" htmlFor="co-job"><Select id="co-job" value={job} placeholder="Not job-specific" onChange={(e) => setJob(e.target.value)} options={(jobs.data ?? []).map((j) => ({ value: j.id, label: `${j.number ? j.number + ' - ' : ''}${j.name}` }))} /></Field>
        <Field label="Against an order" htmlFor="co-order" hint="Matching it to an agreed order shows whether the bill came in higher." className="sm:col-span-2"><Select id="co-order" value={order} placeholder="Not against an order" onChange={(e) => setOrder(e.target.value)} options={agreed.map((o) => ({ value: o.id, label: `${o.number} - ${o.supplier_name} (${formatINR(o.total)})` }))} /></Field>
        <Field label="Notes" htmlFor="co-notes" className="sm:col-span-2"><Textarea id="co-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">Total <strong className="text-foreground">{formatINR(amount + tax)}</strong></p>
      <div className="mt-4 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!vendor.trim() || !(amount > 0)} onClick={() => save.mutate()}>{cost ? 'Fix and resend' : 'Send for approval'}</Button>
      </div>
    </div>
  )
}
