import { useState } from 'react'
import { Download } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Input, Select, Stat, StatGrid, Tabs } from '@/components/ui'
import {
  saveBlock, saveCategory, saveInvoice, saveWorkingRate, trackerExcel, trackerKeys, useTracker,
  type FooterCell, type RmcRow, type StockItem, type SummaryRow, type TrackerInvoice, type TrackerCategory,
} from '@/api/invoiceTracker'
import { countStock, stockKeys } from '@/api/stock'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'

type Tab = 'summary' | 'invoices' | 'materials' | 'rmc' | 'stock'

const TOTAL_HEADS = ['Total qty', 'Total rate', 'Total amount', 'Working rate', 'Working amount', 'Physical store stock']

/** A box that saves what was typed when you leave it, and only if it changed - so a table of them is not a form to submit. */
function EditCell({ value, onSave, type = 'text', label, width = 'w-28', align }: { value: string | number; onSave: (v: string) => void; type?: 'text' | 'number' | 'date'; label: string; width?: string; align?: 'right' }) {
  const [text, setText] = useState(String(value))
  const [seen, setSeen] = useState(String(value))
  if (String(value) !== seen) { setSeen(String(value)); setText(String(value)) }
  const commit = () => { if (text !== String(value)) onSave(text) }
  return <Input aria-label={label} type={type} value={text} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} className={`h-8 px-2 text-[13px] ${width} ${align === 'right' ? 'text-right' : ''}`} {...(type === 'number' ? { step: '0.01', min: 0 } : {})} />
}

/** The lines under each invoice column of a trade: its amount and GST, the bill's own charges, and what the bill printed. */
function footRows(c: TrackerCategory, gst: number) {
  const at = (id: number) => c.footer.find((f) => f.grn_id === id)
  const money = (pick: (f: FooterCell) => number | null) => (id: number) => { const f = at(id); const v = f ? pick(f) : null; return v == null ? '-' : formatINR(v) }
  const sum = (pick: (f: FooterCell) => number | null) => formatINR(c.footer.reduce((a, f) => a + (pick(f) ?? 0), 0))
  const diff = (id: number) => { const f = at(id); return f?.difference == null ? '-' : Math.abs(f.difference) < 1 ? 'matches' : formatINR(f.difference) }
  return [
    { label: 'Amount', cell: money((f) => f.amount), total: sum((f) => f.amount), strong: true },
    { label: `GST ${gst}%`, cell: money((f) => f.gst), total: sum((f) => f.gst) },
    { label: 'Freight', cell: money((f) => f.freight), total: sum((f) => f.freight) },
    { label: 'Insurance', cell: money((f) => f.insurance), total: sum((f) => f.insurance) },
    { label: 'Hamali', cell: money((f) => f.hamali), total: sum((f) => f.hamali) },
    { label: 'Total amount', cell: money((f) => f.total), total: sum((f) => f.total), strong: true },
    { label: 'Invoice amount', cell: money((f) => f.invoice_amount), total: sum((f) => f.invoice_amount) },
    { label: 'Different amount', cell: diff, total: sum((f) => f.difference) },
  ]
}

/** Purchases, and the supplier's own bills checked against what came through the gate. Built from posted goods receipts. */
export default function InvoiceTrackerPage() {
  const { can } = useSession()
  const edit = can('stores.receive|stores.manage|purchase.manage')
  const [tab, setTab] = useState<Tab>('summary')
  const [job, setJob] = useState(0)
  const [gst, setGst] = useState(18)
  const [markup, setMarkup] = useState(20)
  const [cat, setCat] = useState('')
  const q = useTracker(job, gst, markup)
  const t = q.data
  const refresh = { invalidate: [trackerKeys.all], success: false as const }
  const invoice = useAction(saveInvoice, refresh)
  const block = useAction(saveBlock, refresh)
  const note = useAction(saveCategory, refresh)
  const work = useAction(saveWorkingRate, refresh)
  const count = useAction(({ code, qty }: { code: string; qty: number }) => countStock(code, qty), { invalidate: [trackerKeys.all, stockKeys.all] })
  const keep = can('stores.manage')
  const none = !q.isPending && !t?.invoices.length

  const summaryCols: TableColumn<SummaryRow>[] = [
    { id: 'c', header: 'Description', cell: (r) => <span className="font-medium">{r.category}</span>, sort: (r) => r.category },
    { id: 'p', header: 'Purchase amount', align: 'right', cell: (r) => formatINR(r.purchase_amount), sort: (r) => r.purchase_amount },
    { id: 'w', header: 'WO amount', align: 'right', cell: (r) => (
      <div className="flex flex-col items-end gap-0.5">
        {edit ? <EditCell label={`Work order amount for ${r.category}`} type="number" value={r.wo_amount || ''} align="right" onSave={(v) => note.mutate({ job_id: job, category: r.category, wo_amount: Number(v) || 0 })} /> : formatINR(r.wo_amount)}
        {r.wo_source === 'work orders' && <span className="text-[11px] text-muted-foreground">from work orders</span>}
        {r.wo_source === 'typed' && r.wo_suggested > 0 && r.wo_suggested !== r.wo_amount && <span className="text-[11px] text-muted-foreground">work orders say {formatINR(r.wo_suggested)}</span>}
      </div>) },
    { id: 'd', header: 'Difference', align: 'right', cell: (r) => <span className={r.difference < 0 ? 'text-warning' : ''}>{formatINR(r.difference)}</span> },
    { id: 'r', header: 'Remarks', cell: (r) => (edit ? <EditCell label={`Remarks for ${r.category}`} value={r.remarks} width="w-56" onSave={(v) => note.mutate({ job_id: job, category: r.category, remarks: v })} /> : r.remarks) },
  ]

  const invoiceCols: TableColumn<TrackerInvoice>[] = [
    { id: 'n', header: 'Invoice', cell: (i) => <div><span className="font-medium">{i.invoice_number || '-'}</span><div className="text-xs text-muted-foreground">{i.grn} {i.po_number && `- ${i.po_number}`}</div></div>, sort: (i) => i.invoice_number },
    { id: 's', header: 'Supplier', hideBelow: 'md', cell: (i) => i.supplier, sort: (i) => i.supplier },
    { id: 'dt', header: 'Invoice date', cell: (i) => (edit ? <EditCell label={`Invoice date for ${i.invoice_number || i.grn}`} type="date" value={i.invoice_date} width="w-36" onSave={(v) => invoice.mutate({ grnId: i.grn_id, invoice_date: v })} /> : i.invoice_date || '-') },
    { id: 'a', header: 'Amount', align: 'right', hideBelow: 'lg', cell: (i) => formatINR(i.amount) },
    { id: 'g', header: `GST ${gst}%`, align: 'right', hideBelow: 'lg', cell: (i) => formatINR(i.gst) },
    { id: 'f', header: 'Freight', align: 'right', hideBelow: 'md', cell: (i) => (edit ? <EditCell label={`Freight for ${i.invoice_number || i.grn}`} type="number" value={i.freight || ''} align="right" width="w-24" onSave={(v) => invoice.mutate({ grnId: i.grn_id, freight: Number(v) || 0 })} /> : formatINR(i.freight)) },
    { id: 'ins', header: 'Insurance', align: 'right', hideBelow: 'xl', cell: (i) => (edit ? <EditCell label={`Insurance for ${i.invoice_number || i.grn}`} type="number" value={i.insurance || ''} align="right" width="w-24" onSave={(v) => invoice.mutate({ grnId: i.grn_id, insurance: Number(v) || 0 })} /> : formatINR(i.insurance)) },
    { id: 'ham', header: 'Hamali', align: 'right', hideBelow: 'xl', cell: (i) => (edit ? <EditCell label={`Hamali for ${i.invoice_number || i.grn}`} type="number" value={i.hamali || ''} align="right" width="w-24" onSave={(v) => invoice.mutate({ grnId: i.grn_id, hamali: Number(v) || 0 })} /> : formatINR(i.hamali)) },
    { id: 't', header: 'Total', align: 'right', cell: (i) => <span className="font-medium">{formatINR(i.total)}</span> },
    { id: 'p', header: 'Invoice amount', align: 'right', cell: (i) => (edit ? <EditCell label={`Amount on the supplier's bill ${i.invoice_number || i.grn}`} type="number" value={i.invoice_amount ?? ''} align="right" width="w-32" onSave={(v) => invoice.mutate(v === '' ? { grnId: i.grn_id, clear_amount: true } : { grnId: i.grn_id, invoice_amount: Number(v) })} /> : i.invoice_amount == null ? '-' : formatINR(i.invoice_amount)) },
    { id: 'rm', header: 'Remarks', hideBelow: 'xl', cell: (i) => (edit ? <EditCell label={`Remark on invoice ${i.invoice_number || i.grn}`} value={i.remark} width="w-48" onSave={(v) => invoice.mutate({ grnId: i.grn_id, remark: v })} /> : i.remark) },
    { id: 'x', header: 'Difference', align: 'right', cell: (i) => (i.difference == null ? <span className="text-xs text-muted-foreground">not checked</span> : Math.abs(i.difference) < 1 ? <Badge tone="success" dot>matches</Badge> : <Badge tone="danger" dot>{formatINR(i.difference)}</Badge>) },
  ]

  const stockCols: TableColumn<StockItem>[] = [
    { id: 'c', header: 'Material', cell: (i) => <div><span className="font-medium">{i.item_name}</span><div className="font-mono text-xs text-muted-foreground">{i.item_code}</div></div>, sort: (i) => i.item_name },
    { id: 'u', header: 'UOM', hideBelow: 'sm', cell: (i) => i.uom },
    { id: 'b', header: 'Physical store stock', align: 'right', cell: (i) => (keep
      ? <EditCell label={`Physical stock of ${i.item_code}`} type="number" value={i.counted ? i.on_hand : ''} align="right" width="w-28" onSave={(v) => { if (v !== '' && Number(v) >= 0) count.mutate({ code: i.item_code, qty: Number(v) }) }} />
      : i.counted ? i.on_hand : '-') },
  ]

  const rmcCols: TableColumn<RmcRow>[] = [
    { id: 'n', header: '#', width: '3rem', cell: (r) => r.n },
    { id: 'd', header: 'Date', cell: (r) => r.invoice_date, sort: (r) => r.invoice_date },
    { id: 's', header: 'Supplier', hideBelow: 'lg', cell: (r) => r.supplier },
    { id: 'po', header: 'PO number', hideBelow: 'xl', cell: (r) => r.po_number },
    { id: 'v', header: 'Vehicle', cell: (r) => r.vehicle || '-' },
    { id: 'i', header: 'Invoice no', cell: (r) => r.invoice_number || '-' },
    { id: 'g', header: 'Grade', cell: (r) => r.grade || '-' },
    { id: 'q', header: 'Qty (cum)', align: 'right', cell: (r) => r.qty },
    { id: 'r', header: 'Unit price', align: 'right', hideBelow: 'md', cell: (r) => formatINR(r.rate) },
    { id: 'a', header: 'Amount', align: 'right', cell: (r) => formatINR(r.amount) },
    { id: 'b', header: 'Block', cell: (r) => (edit ? <EditCell label={`Block for ${r.invoice_number || `load ${r.n}`}`} value={r.block} width="w-32" onSave={(v) => block.mutate({ lineId: r.line_id, block: v })} /> : r.block || '-') },
  ]

  const shown: TrackerCategory | undefined = t?.categories.find((c) => c.name === cat) ?? t?.categories[0]
  const cols = (shown?.invoice_ids ?? []).map((id) => t?.invoices.find((i) => i.grn_id === id)).filter((i): i is TrackerInvoice => !!i)

  return (
    <>
      <PageHeader
        eyebrow="Store"
        title="Invoice Tracker"
        description="Every purchase by trade and supplier invoice, checked against what came through the gate. Built from posted goods receipts."
        actions={<Button variant="outline" asChild><a href={trackerExcel(job, gst, markup)}><Download /> Excel</a></Button>}
      />
      <div className="mb-6 flex flex-wrap items-end gap-4">
        <ProjectPicker value={job} onChange={setJob} allowAll className="w-full max-w-sm" />
        <label className="grid gap-1 text-[13px] font-medium">GST %<Input aria-label="GST percent" type="number" min={0} max={100} step="0.5" value={gst} onChange={(e) => setGst(Math.max(0, Math.min(100, Number(e.target.value) || 0)))} className="h-10 w-24" /></label>
        <label className="grid gap-1 text-[13px] font-medium" title="Installation, consumables, wastage, overhead and profit, on the basic rate">Markup %<Input aria-label="Markup percent" type="number" min={0} max={100} step="0.5" value={markup} onChange={(e) => setMarkup(Math.max(0, Math.min(100, Number(e.target.value) || 0)))} className="h-10 w-24" /></label>
      </div>
      <StatGrid>
        <Stat label="Purchases (with GST)" value={formatINR(t?.summary.purchase_amount ?? 0)} loading={q.isPending} />
        <Stat label="Supplier invoices" value={t?.totals.invoices ?? 0} loading={q.isPending} />
        <Stat label="Bill not yet checked" value={t?.totals.unchecked ?? 0} tone={t?.totals.unchecked ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Bills that do not match" value={t?.totals.mismatched ?? 0} tone={t?.totals.mismatched ? 'danger' : undefined} loading={q.isPending} />
      </StatGrid>
      <div className="mb-4">
        <Tabs label="Invoice tracker" value={tab} onChange={setTab} items={[
          { value: 'summary', label: 'Summary', info: 'Purchases by trade against the work-order value, with a remark for each.' },
          { value: 'invoices', label: 'Invoices', count: t?.invoices.length, info: 'One row per supplier invoice: key in its date, freight and the amount printed on the bill to see whether it matches.' },
          { value: 'materials', label: 'Received materials', info: 'Each material down the page and each supplier invoice across, with quantity, rate and amount.' },
          { value: 'stock', label: 'Physical stock', info: 'Every purchased material and what the store holds now. Key in a count and the difference is posted to stock.' },
          { value: 'rmc', label: 'Ready-mix register', count: t?.rmc.rows.length, info: 'A row for every lorry of concrete, with the block it went into and a total for each block.' },
        ]} />
      </div>

      {tab === 'summary' && (
        <DataTable label="Summary by trade" rows={t?.summary.rows ?? []} columns={summaryCols} rowKey={(r) => r.category} loading={q.isPending}
          empty="Nothing purchased yet. Post a goods receipt and it appears here."
          footer={t && t.summary.rows.length > 0 ? <div className="flex flex-wrap justify-between gap-3 px-4 py-3 text-sm font-semibold"><span>Total amount</span><span>Purchase {formatINR(t.summary.purchase_amount)}</span><span>WO {formatINR(t.summary.wo_amount)}</span><span>Difference {formatINR(t.summary.difference)}</span></div> : undefined} />
      )}

      {tab === 'invoices' && (
        <DataTable label="Supplier invoices" rows={t?.invoices ?? []} columns={invoiceCols} rowKey={(i) => i.grn_id} loading={q.isPending}
          empty="No posted goods receipts yet."
          footer={t && !none ? <div className="flex flex-wrap justify-between gap-3 px-4 py-3 text-sm font-semibold"><span>Total</span><span>Amount {formatINR(t.totals.amount)}</span><span>GST {formatINR(t.totals.gst)}</span><span>Freight {formatINR(t.totals.freight)}</span><span>Insurance {formatINR(t.totals.insurance)}</span><span>Hamali {formatINR(t.totals.hamali)}</span><span>{formatINR(t.totals.total)}</span></div> : undefined} />
      )}

      {tab === 'materials' && (
        none ? <p className="rounded-xl border border-border p-8 text-center text-muted-foreground">No posted goods receipts yet.</p> : (
          <div className="grid gap-4">
            <div className="max-w-xs"><Select aria-label="Trade" value={shown?.name ?? ''} onChange={(e) => setCat(e.target.value)} options={(t?.categories ?? []).map((c) => ({ value: c.name, label: c.name }))} /></div>
            {shown && (
              <div className="overflow-x-auto rounded-xl border border-border">
                <table className="w-full border-collapse text-[13px]">
                  <thead className="bg-muted/60">
                    <tr>
                      <th rowSpan={5} className="w-12 px-2 py-2 text-center">SL NO</th>
                      <th rowSpan={5} className="sticky left-0 z-10 min-w-56 bg-muted px-3 py-2 text-left">Material description</th>
                      <th rowSpan={5} className="px-3 py-2 text-left">UOM</th>
                      {cols.map((i) => <th key={i.grn_id} colSpan={3} className="border-l border-border px-3 py-1.5 text-center font-semibold">{i.supplier}</th>)}
                      {TOTAL_HEADS.map((h) => <th key={h} rowSpan={5} className="border-l border-border px-2 py-1.5 text-right">{h}</th>)}
                    </tr>
                    <tr>{cols.map((i) => <th key={i.grn_id} colSpan={3} className="border-l border-border px-3 py-1 text-center font-normal text-muted-foreground">{i.invoice_date || i.received_on}</th>)}</tr>
                    <tr>{cols.map((i) => <th key={i.grn_id} colSpan={3} className="border-l border-border px-3 py-1 text-center font-normal text-muted-foreground">{i.invoice_number || i.grn}</th>)}</tr>
                    <tr>{cols.map((i) => <th key={i.grn_id} colSpan={3} className="border-l border-border px-3 py-1 text-center font-normal text-muted-foreground">{i.po_number ? `PO ${i.po_number}` : '-'}</th>)}</tr>
                    <tr className="text-xs text-muted-foreground">
                      {cols.map((i) => <><th key={`${i.grn_id}q`} className="border-l border-border px-2 py-1 text-right">Qty</th><th key={`${i.grn_id}r`} className="px-2 py-1 text-right">Rate</th><th key={`${i.grn_id}a`} className="px-2 py-1 text-right">Amount</th></>)}
                    </tr>
                  </thead>
                  <tbody>
                    {shown.materials.map((m) => {
                      const got = m.cells.length > 0
                      return (
                        <tr key={m.key} className="border-t border-border">
                          <td className="px-2 py-2 text-center text-muted-foreground">{m.sl}</td>
                          <td className="sticky left-0 bg-card px-3 py-2"><span className="font-medium">{m.description}</span>{m.item_code && <div className="font-mono text-xs text-muted-foreground">{m.item_code}</div>}</td>
                          <td className="px-3 py-2">{m.uom}</td>
                          {cols.map((i) => { const c = m.cells.find((x) => x.grn_id === i.grn_id); return c ? <><td key={`${i.grn_id}q`} className="border-l border-border px-2 py-2 text-right tabular">{c.qty}</td><td key={`${i.grn_id}r`} className="px-2 py-2 text-right tabular">{c.rate}</td><td key={`${i.grn_id}a`} className="px-2 py-2 text-right tabular">{formatINR(c.amount)}</td></> : <td key={i.grn_id} colSpan={3} className="border-l border-border" /> })}
                          <td className="border-l border-border px-2 py-2 text-right font-medium tabular">{got ? m.total_qty : '-'}</td>
                          <td className="px-2 py-2 text-right tabular">{got ? m.total_rate : '-'}</td>
                          <td className="px-2 py-2 text-right font-medium tabular">{got ? formatINR(m.total_amount) : '-'}</td>
                          <td className="px-2 py-1 text-right">{edit
                            ? <EditCell label={`Working rate for ${m.item_code || m.description}`} type="number" value={m.working_rate ?? ''} align="right" width="w-24" onSave={(v) => work.mutate({ job_id: job, item_key: m.key, rate: v === '' ? null : Number(v) })} />
                            : m.working_rate == null ? '-' : m.working_rate}</td>
                          <td className="px-2 py-2 text-right tabular">{m.working_amount == null ? '-' : formatINR(m.working_amount)}</td>
                          <td className="px-2 py-2 text-right tabular">{m.counted ? m.on_hand : '-'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                  <tfoot className="border-t-2 border-border bg-muted/40">
                    {footRows(shown, gst).map((r) => (
                      <tr key={r.label} className={r.strong ? 'font-semibold' : 'text-muted-foreground'}>
                        <td colSpan={3} className="sticky left-0 bg-muted px-3 py-1.5 text-right">{r.label}</td>
                        {cols.map((i) => <td key={i.grn_id} colSpan={3} className="border-l border-border px-2 py-1.5 text-right tabular">{r.cell(i.grn_id)}</td>)}
                        <td className="border-l border-border" /><td /><td className="px-2 py-1.5 text-right tabular">{r.total}</td>
                        <td />{r.label === 'Amount' ? <td className="px-2 py-1.5 text-right tabular">{shown.working_total ? formatINR(shown.working_total) : ''}</td> : <td />}<td />
                      </tr>
                    ))}
                    <tr className="text-muted-foreground">
                      <td colSpan={3} className="sticky left-0 bg-muted px-3 py-1.5 text-right">Remarks</td>
                      {cols.map((i) => <td key={i.grn_id} colSpan={3} className="border-l border-border px-2 py-1.5 text-right">{edit
                        ? <EditCell label={`Remark on invoice ${i.invoice_number || i.grn}`} value={i.remark} width="w-full min-w-40" onSave={(v) => invoice.mutate({ grnId: i.grn_id, remark: v })} />
                        : i.remark}</td>)}
                      <td colSpan={6} />
                    </tr>
                    <tr className="border-t border-border">
                      <td colSpan={3 + cols.length * 3 + 2} className="px-3 py-1.5 text-right text-muted-foreground">Installation + consumables + wastage + overhead and profit on the basic rate @ {markup}%</td>
                      <td className="px-2 py-1.5 text-right tabular">{formatINR(shown.markup)}</td><td colSpan={3} />
                    </tr>
                    <tr className="font-semibold">
                      <td colSpan={3 + cols.length * 3 + 2} className="px-3 py-1.5 text-right">{shown.name} total with markup (before GST)</td>
                      <td className="px-2 py-1.5 text-right tabular">{formatINR(shown.with_markup)}</td><td colSpan={3} />
                    </tr>
                    {shown.note && <tr><td colSpan={3 + cols.length * 3 + 6} className="px-3 py-2 text-left font-medium">Note: {shown.note}</td></tr>}
                  </tfoot>
                </table>
              </div>
            )}
          </div>
        )
      )}

      {tab === 'stock' && (
        <div className="grid gap-6">
          {!q.isPending && !t?.stock.length && <p className="rounded-xl border border-border p-8 text-center text-muted-foreground">No purchased materials in the item master yet.</p>}
          {(t?.stock ?? []).map((g) => (
            <div key={g.category}>
              <h3 className="mb-2 text-base font-semibold">{g.category}</h3>
              <DataTable label={`Physical stock: ${g.category}`} rows={g.items} columns={stockCols} rowKey={(i) => i.item_code} />
            </div>
          ))}
          {!keep && !!t?.stock.length && <p className="text-[13px] text-muted-foreground">Counting stock needs the stores right. You can see what the store holds.</p>}
        </div>
      )}

      {tab === 'rmc' && (
        <div className="grid gap-6">
          <DataTable label="Ready-mix deliveries" rows={t?.rmc.rows ?? []} columns={rmcCols} rowKey={(r) => r.line_id} loading={q.isPending}
            empty="No ready-mix deliveries yet. Concrete is picked out by its category or name (RMC, ready mix, concrete)."
            footer={t && t.rmc.rows.length > 0 ? <div className="flex flex-wrap justify-between gap-3 px-4 py-3 text-sm font-semibold"><span>{t.rmc.qty} cum</span><span>Amount {formatINR(t.rmc.amount)}</span><span>GST {formatINR(t.rmc.gst)}</span><span>Total {formatINR(t.rmc.total)}</span></div> : undefined} />
          {!!t?.rmc.blocks.length && (
            <div>
              <h3 className="mb-2 text-base font-semibold">By block</h3>
              <DataTable label="Ready-mix by block" rows={t.rmc.blocks} rowKey={(b) => b.block}
                columns={[
                  { id: 'b', header: 'Block', cell: (b) => <span className="font-medium">{b.block}</span> },
                  { id: 'l', header: 'Loads', align: 'right', cell: (b) => b.loads },
                  { id: 'q', header: 'Qty (cum)', align: 'right', cell: (b) => b.qty },
                  { id: 'a', header: 'Amount', align: 'right', cell: (b) => formatINR(b.amount) },
                ]} />
            </div>
          )}
        </div>
      )}
    </>
  )
}
