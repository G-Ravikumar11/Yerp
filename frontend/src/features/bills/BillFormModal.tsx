import { useEffect, useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { billKeys, CATEGORIES, createBill, nextBillNumber, updateBill, useTaxRates, type BillInput, type SupplierBill } from '@/api/bills'
import { useSuppliers } from '@/api/ledger'
import { usePurchaseOrders } from '@/api/purchaseOrders'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const blank = (): BillInput => ({ number: '', vendor_name: '', vendor_email: '', category: 'general', issue_date: today(), due_date: '', amount: 0, tax_amount: 0, total: 0, reference: '', notes: '', purchase_order_id: null })

export function BillFormModal({ open, bill, onClose }: { open: boolean; bill: SupplierBill | null; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="lg" title={bill ? `Edit ${bill.number}` : 'New bill'}>
      {open && <Form key={bill?.id ?? 'new'} bill={bill} onClose={onClose} />}
    </Modal>
  )
}

function Form({ bill, onClose }: { bill: SupplierBill | null; onClose: () => void }) {
  const [f, setF] = useState<BillInput>(() => (bill ? { ...blank(), ...bill } : blank()))
  const [rate, setRate] = useState('')
  const rates = useTaxRates()
  const suppliers = useSuppliers()
  const orders = usePurchaseOrders(false)
  useEffect(() => {
    if (!bill) void nextBillNumber().then((n) => setF((s) => (s.number ? s : { ...s, number: n }))).catch(() => undefined)
  }, [bill])

  const set = (k: keyof BillInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  // The tax follows the amount under a chosen rate; "enter it myself" leaves it alone.
  const money = (amount: number, tax: number) => ({ amount, tax_amount: tax, total: Math.round((amount + tax) * 100) / 100 })
  const setAmount = (n: number) => setF((s) => ({ ...s, ...money(n, rate ? Math.round(n * Number(rate)) / 100 : s.tax_amount) }))
  const pickRate = (v: string) => {
    setRate(v)
    if (v) setF((s) => ({ ...s, ...money(s.amount, Math.round(s.amount * Number(v)) / 100) }))
  }
  // Orders that have been agreed (only those can be matched), this supplier's first when one is named.
  const committed = (orders.data ?? []).filter((o) => o.approval_status === 'approved' || ['Approved', 'Closed'].includes(o.status) || o.id === f.purchase_order_id)
  const sameSupplier = (o: { supplier_name: string }) => !f.vendor_name.trim() || o.supplier_name.trim().toLowerCase() === f.vendor_name.trim().toLowerCase()
  const poOptions = [...committed.filter(sameSupplier), ...committed.filter((o) => !sameSupplier(o))].map((o) => ({ value: String(o.id), label: `${o.number} - ${o.supplier_name} (${formatINR(o.total)})` }))
  const names = [...(suppliers.data?.suppliers ?? []).map((s) => s.name), ...(suppliers.data?.unregistered ?? [])]
  const save = useAction(() => (bill ? updateBill(bill.id, f) : createBill(f)), { invalidate: [billKeys.all], success: (r) => [bill ? 'Bill updated' : 'Bill created', ...(r?.warnings ?? [])].join('. '), onSuccess: onClose })
  const ready = f.number.trim() && f.vendor_name.trim()

  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Bill number *" htmlFor="bf-number"><Input id="bf-number" value={f.number} onChange={set('number')} placeholder="BILL-0001" /></Field>
        <Field label="Vendor name *" htmlFor="bf-vendor">
          <Input id="bf-vendor" list="bf-suppliers" autoComplete="off" value={f.vendor_name} onChange={set('vendor_name')} placeholder="Supplier's name" />
          <datalist id="bf-suppliers">{names.map((n) => <option key={n} value={n} />)}</datalist>
        </Field>
        <Field label="Vendor email" htmlFor="bf-email"><Input id="bf-email" type="email" value={f.vendor_email} onChange={set('vendor_email')} placeholder="billing@supplier.com" /></Field>
        <Field label="Category" htmlFor="bf-cat"><Select id="bf-cat" value={f.category} onChange={set('category')} options={CATEGORIES.map((c) => ({ value: c, label: c.charAt(0).toUpperCase() + c.slice(1) }))} /></Field>
        <Field label="Issue date" htmlFor="bf-issue"><Input id="bf-issue" type="date" value={f.issue_date} onChange={set('issue_date')} /></Field>
        <Field label="Due date" htmlFor="bf-due"><Input id="bf-due" type="date" value={f.due_date} onChange={set('due_date')} /></Field>
        <Field label="Amount" htmlFor="bf-amount"><NumField id="bf-amount" value={f.amount} onValue={setAmount} /></Field>
        <Field label="Tax rate" htmlFor="bf-rate"><Select id="bf-rate" value={rate} onChange={(e) => pickRate(e.target.value)} placeholder="Enter it myself" options={(rates.data ?? []).map((r) => ({ value: String(r.percent), label: r.label }))} /></Field>
        <Field label="Tax" htmlFor="bf-tax"><NumField id="bf-tax" value={f.tax_amount} onValue={(n) => { setRate(''); setF((s) => ({ ...s, ...money(s.amount, n) })) }} /></Field>
        <Field label="Total" htmlFor="bf-total"><Input id="bf-total" readOnly value={formatINR(f.total)} className="bg-muted/40" /></Field>
        <Field label="Supplier's invoice number" htmlFor="bf-ref"><Input id="bf-ref" value={f.reference} onChange={set('reference')} placeholder="As printed on their invoice" /></Field>
        <Field label="Purchase order" htmlFor="bf-po"><Select id="bf-po" value={f.purchase_order_id ? String(f.purchase_order_id) : ''} onChange={(e) => setF((s) => ({ ...s, purchase_order_id: e.target.value ? Number(e.target.value) : null }))} placeholder="None" options={poOptions} /></Field>
        <Field label="Notes" htmlFor="bf-notes" className="sm:col-span-2"><Textarea id="bf-notes" rows={2} value={f.notes} onChange={set('notes')} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!ready} onClick={() => save.mutate()}>Save bill</Button>
      </div>
    </div>
  )
}
