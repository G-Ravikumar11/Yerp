import { useEffect, useMemo, useState } from 'react'
import { FileUp } from 'lucide-react'
import { DataGrid, type Column } from '@/components/grid'
import { Button, Field, Input, Modal, Select, Textarea } from '@/components/ui'
import { GST_RATES, poKeys, savePo, type PoInput, type PurchaseOrder } from '@/api/purchaseOrders'
import { useItems } from '@/api/items'
import { useSuppliers } from '@/api/ledger'
import { useJobOptions } from '@/api/clientOrders'
import { AiPanel } from './AiPanel'
import { SheetImportModal } from '@/features/sheetimport/SheetImportModal'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { checkOrder, useBudgetHeads, useContractRates, type OrderCheck } from '@/api/poControls'
import { useDebounced } from '@/lib/hooks'

interface Row {
  item_code: string
  description: string
  qty: number | null
  uom: string
  price: number | null
  tax: string
  boq_key: string
}

const blank = (): Row => ({ item_code: '', description: '', qty: null, uom: '', price: null, tax: '18', boq_key: '' })
const rateOf = (t: string) => Number(String(t).replace(/[^0-9.]/g, '')) || 0
const lineAmount = (r: Row) => (r.qty ?? 0) * (r.price ?? 0)

export function OrderFormModal({ open, order, staff, onClose }: { open: boolean; order: PurchaseOrder | null; staff: boolean; onClose: () => void }) {
  const about = staff ? 'This goes to your manager for approval before you commit to it.' : 'What is being bought, line by line. Each line can be received against when the lorry arrives.'
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="xl" title={order ? `Edit ${order.number}` : staff ? 'Raise an order' : 'New purchase order'} description={about}>
      {open && <Form key={order?.id ?? 'new'} order={order} staff={staff} onClose={onClose} />}
    </Modal>
  )
}

function Form({ order, staff, onClose }: { order: PurchaseOrder | null; staff: boolean; onClose: () => void }) {
  const jobs = useJobOptions(staff)
  const rm = useItems('RM', '')
  const suppliers = useSuppliers()
  const [supplier, setSupplier] = useState(order?.supplier_name ?? '')
  const [job, setJob] = useState(order?.job_id ? String(order.job_id) : '')
  const [issue, setIssue] = useState(order?.issue_date ?? today())
  const [needed, setNeeded] = useState(order?.needed_by ?? '')
  const [notes, setNotes] = useState(order?.notes ?? '')
  const [rows, setRows] = useState<Row[]>(() => (order?.line_items ?? []).map((l) => ({ item_code: l.item_code, description: l.description, qty: l.qty, uom: l.uom, price: l.price, tax: String(rateOf(l.tax_rate)), boq_key: l.boq_key ?? '' })))
  const [reason, setReason] = useState(order?.budget_reason ?? '')
  const heads = useBudgetHeads(Number(job) || 0)
  const contract = useContractRates(supplier)
  // The supplier named after the items were chosen: their contract rates fill the lines still without a rate.
  useEffect(() => {
    const agreed = contract.data
    if (!agreed) return
    setRows((cur) => (cur.some((r) => r.item_code && !r.price && agreed[r.item_code]) ? cur.map((r) => (r.item_code && !r.price && agreed[r.item_code] ? { ...r, price: agreed[r.item_code] } : r)) : cur))
  }, [contract.data])
  const [importing, setImporting] = useState(false)
  const master = useMemo(() => new Map((rm.data?.items ?? []).map((i) => [i.item_code, i])), [rm.data])

  const columns = useMemo<Column<Row>[]>(
    () => [
      {
        id: 'item_code',
        header: 'Item',
        hint: 'From the item master',
        type: 'select',
        width: 230,
        pin: true,
        options: (rm.data?.items ?? []).map((i) => ({ value: i.item_code, label: `${i.item_code} - ${i.item_name}` })),
        // Choosing an item brings its name and unit, and its rate: the supplier's rate contract in force, or else the rate
        // it was last bought at - unless one is already typed.
        set: (r, v) => {
          const it = master.get(String(v))
          const agreed = contract.data?.[String(v)]
          return { ...r, item_code: String(v ?? ''), description: r.description || it?.item_name || '', uom: r.uom || it?.units_of_measure || '', price: agreed || r.price || it?.last_rate || null }
        },
      },
      { id: 'description', header: 'Description', width: 230, placeholder: 'Crane hire, 2 days' },
      { id: 'qty', header: 'Quantity', type: 'number', width: 100 },
      { id: 'uom', header: 'Unit', width: 80 },
      { id: 'price', header: 'Rate', type: 'number', decimals: 2, width: 110 },
      { id: 'tax', header: 'GST %', type: 'select', width: 90, options: GST_RATES.map(String), empty: '18', countsAsData: false },
      { id: 'amount', header: 'Amount', type: 'number', decimals: 2, width: 130, readOnly: true, get: (r) => lineAmount(r) || null, summary: 'sum' },
      // Charged to a BOQ line or heading of the job: its budget is checked as the order is filled in.
      { id: 'boq_key', header: 'BOQ item', hint: 'Its budget is checked', type: 'select', width: 230, countsAsData: false,
        options: (heads.data ?? []).map((h) => ({ value: h.key, label: `${h.heading ? '[heading] ' : ''}${h.label}` })) },
    ],
    [rm.data, master, heads.data, contract.data],
  )

  // The lines as they are on screen, counting a number still being typed into a cell.
  const [draft, setDraft] = useState<Row[] | null>(null)
  const live = draft ?? rows
  const lines = live.filter((r) => (r.qty ?? 0) > 0 && (r.item_code || r.description.trim()))
  const amount = lines.reduce((t, r) => t + lineAmount(r), 0)
  const tax = lines.reduce((t, r) => t + (lineAmount(r) * rateOf(r.tax)) / 100, 0)
  // Why Save is greyed out, in words: the first box still to fill, so nobody is left guessing.
  const missing = (() => {
    if (!supplier.trim()) return 'fill in the Supplier'
    if (lines.length && amount > 0) return null
    const started = live.map((r, i) => ({ r, n: i + 1 })).filter(({ r }) => r.item_code || r.description.trim() || r.qty || r.price)
    if (!started.length) return 'add a line - choose an Item or write a Description'
    for (const { r, n } of started) {
      if (!r.item_code && !r.description.trim()) return `line ${n} needs an Item or a Description`
      if (!((r.qty ?? 0) > 0)) return `line ${n} needs a Quantity`
      if (!((r.price ?? 0) > 0)) return `line ${n} needs a Rate`
    }
    return 'the order comes to nothing'
  })()
  const save = useAction(
    () => {
      const body: PoInput = { supplier_name: supplier.trim(), amount, tax_amount: Math.round(tax * 100) / 100, total: Math.round((amount + tax) * 100) / 100, issue_date: issue, needed_by: needed, notes: notes.trim(), job_id: job ? Number(job) : null, budget_reason: reason.trim(), line_items: lines.map((r) => ({ item_code: r.item_code, description: r.description || r.item_code, uom: r.uom, qty: r.qty ?? 0, price: r.price ?? 0, tax_rate: `${rateOf(r.tax)}%`, boq_key: r.boq_key })) }
      return savePo(order?.id ?? null, body, staff)
    },
    { invalidate: [poKeys.all, ['approvals']], onSuccess: onClose },
  )
  const fromSheet = (r: { [k: string]: string | number | null }[]) =>
    setRows((cur) => [...cur.filter((x) => x.item_code || x.description || x.qty), ...r.map((x) => ({ item_code: master.has(String(x.item_code ?? '')) ? String(x.item_code) : '', description: String(x.description || x.item_code || ''), qty: Number(x.qty) || 0, uom: String(x.uom ?? ''), price: Number(x.price) || 0, tax: '18' }))])
  const names = [...(suppliers.data?.suppliers ?? []).map((s) => s.name), ...(suppliers.data?.unregistered ?? [])]

  // The budget and the prices, checked as the order is filled in (a moment after the typing stops).
  const asked = useDebounced(JSON.stringify({ job, supplier: supplier.trim(), lines: lines.map((r) => [r.item_code, r.boq_key, r.qty, r.price, r.description]) }), 500)
  const [check, setCheck] = useState<OrderCheck | null>(null)
  useEffect(() => {
    const a = JSON.parse(asked) as { job: string; supplier: string; lines: [string, string, number | null, number | null, string][] }
    if (!a.lines.length) { setCheck(null); return }
    let live = true
    checkOrder({ job_id: a.job ? Number(a.job) : null, supplier_name: a.supplier, order_id: order?.id ?? null,
      line_items: a.lines.map(([item_code, boq_key, qty, price, description]) => ({ item_code, boq_key, qty: qty ?? 0, price: price ?? 0, description })) })
      .then((c) => live && setCheck(c)).catch(() => live && setCheck(null))
    return () => { live = false }
  }, [asked, order?.id])
  const needsReason = !!check?.over_budget && reason.trim().length < 5

  return (
    <div>
      {order && <AiPanel orderId={order.id} />}
      <div className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Supplier" htmlFor="po-supplier">
          <Input id="po-supplier" list="po-suppliers" autoComplete="off" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
          <datalist id="po-suppliers">{names.map((n) => <option key={n} value={n} />)}</datalist>
        </Field>
        <Field label="Job" htmlFor="po-job"><Select id="po-job" value={job} onChange={(e) => setJob(e.target.value)} placeholder="Not for one job" options={(jobs.data ?? []).map((j) => ({ value: j.id, label: `${j.number} - ${j.name}` }))} /></Field>
        <Field label="Date" htmlFor="po-issue"><Input id="po-issue" type="date" value={issue} onChange={(e) => setIssue(e.target.value)} /></Field>
        <Field label="Needed by" htmlFor="po-needed"><Input id="po-needed" type="date" value={needed} onChange={(e) => setNeeded(e.target.value)} /></Field>
      </div>
      <div className="mb-2 flex justify-end"><Button variant="outline" size="sm" onClick={() => setImporting(true)}><FileUp /> Lines from Excel</Button></div>
      <DataGrid aria-label="Order lines" columns={columns} rows={rows} onRowsChange={setRows} onDraft={setDraft} newRow={blank} minRows={5} maxHeight={280} />
      {check && (check.over_budget || check.rates.length > 0) && (
        <div role="alert" className="mt-4 grid gap-2 rounded-lg border border-warning/40 bg-warning-soft p-3 text-[13px]">
          {check.budget.filter((b) => b.over_by > 0.5).map((b) => (
            <p key={b.key}><strong className="text-danger">Over the budget: {b.label}</strong> - budget {formatINR(b.budget ?? 0)}, spent {formatINR(b.spent ?? 0)}, on other orders {formatINR(b.committed ?? 0)}, this order {formatINR(b.this)}: <strong>{formatINR(b.over_by)} over</strong>.</p>
          ))}
          {check.over_budget && (
            <Field label="Why it goes over the budget" htmlFor="po-reason" hint="Needed to save it. The order then also goes to the Master to approve.">
              <Textarea id="po-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Raft thickened by the structural consultant (variation to follow)" />
            </Field>
          )}
          {check.rates.map((r) => <p key={r.item_code}><strong>Rate alert - {r.description || r.item_code}:</strong> {formatINR(r.rate)} is {r.why}.</p>)}
        </div>
      )}
      {check && !check.over_budget && check.budget.some((b) => b.budget != null) && (
        <p className="mt-3 text-xs text-muted-foreground">Within the budget: {check.budget.filter((b) => b.budget != null).map((b) => `${b.label} - ${formatINR((b.budget ?? 0) - (b.spent ?? 0) - (b.committed ?? 0) - b.this)} left`).join('; ')}.</p>
      )}
      <Field label="Notes" htmlFor="po-notes" className="mt-4"><Textarea id="po-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <p className="text-sm">Amount {formatINR(amount)} · GST {formatINR(tax)} · <strong className="tabular">total {formatINR(amount + tax)}</strong></p>
        <div className="flex items-center gap-2">
          {save.error && <p role="alert" className="text-[13px] text-danger">{save.error.message}</p>}
          {!save.error && (missing || needsReason) && <p className="text-[13px] text-muted-foreground">To save, {missing || 'say why it goes over the budget'}.</p>}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} disabled={!!missing || needsReason} onClick={() => save.mutate()}>{staff && !order ? 'Send for approval' : 'Save'}</Button>
        </div>
      </div>
      <SheetImportModal open={importing} onOpenChange={setImporting} kind="po_lines" title="Order lines from Excel" intro="A supplier's quotation or a site's requirement list: read, checked and corrected here, then put on the order." confirmLabel="Put these on the order" invalidate={[]} onRows={fromSheet} />
    </div>
  )
}
