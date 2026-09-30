import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Download, Plus, X } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Field, Input, NumField, Skeleton, Stat, StatGrid } from '@/components/ui'
import { actOnEstimate, addEstimateItem, estimateKeys, removeEstimateItem, saveEstimateHead, useEstimate, type Estimate, type EstimateItem } from '@/api/estimates'
import { useAction } from '@/lib/mutate'
import { formatQty } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { ESTIMATE_TONE } from './EstimatesPage'
import { RateAnalysisModal } from './RateAnalysisModal'

type Act = 'submit' | 'win' | 'lose' | 'reopen' | 'withdraw'

export default function EstimatePage() {
  const id = Number(useParams().id)
  const q = useEstimate(id)
  const e = q.data
  const [rating, setRating] = useState<EstimateItem | null>(null)
  const [removing, setRemoving] = useState<EstimateItem | null>(null)
  const [asking, setAsking] = useState<Act | null>(null)
  const [item, setItem] = useState({ item_no: '', description: '', uom: '', quantity: 0, cost_rate: 0 })
  const refresh = [estimateKeys.all, ['leads']]

  const head = useAction((b: { overhead_percent: number; profit_percent: number }) => saveEstimateHead(e as Estimate, b), { invalidate: refresh, success: false })
  const add = useAction(() => addEstimateItem(id, item), { invalidate: refresh, success: false, onSuccess: () => setItem({ item_no: '', description: '', uom: '', quantity: 0, cost_rate: 0 }) })
  const remove = useAction((it: EstimateItem) => removeEstimateItem(id, it.id), { invalidate: refresh, success: false, onSuccess: () => setRemoving(null) })
  const act = useAction((a: { action: Act; reason?: string }) => actOnEstimate(id, a.action, a.reason), { invalidate: [...refresh, ['client-orders']], onSuccess: () => setAsking(null) })

  if (q.isPending) return <Skeleton className="h-64 w-full" />
  if (!e) return <p role="alert" className="py-10 text-center text-sm text-danger">Could not open that estimate.</p>
  const locked = !e.editable

  const columns: TableColumn<EstimateItem>[] = [
    { id: 'no', header: 'No.', width: '4rem', cell: (it) => <span className="font-mono text-[13px]">{it.item_no}</span> },
    {
      id: 'desc',
      header: 'Item',
      cell: (it) => (
        <div className="max-w-md">
          {it.description}
          {it.fg_code && <div className="font-mono text-xs text-muted-foreground">{it.fg_code}</div>}
        </div>
      ),
    },
    { id: 'qty', header: 'Quantity', align: 'right', cell: (it) => `${formatQty(it.quantity)} ${it.uom}` },
    {
      id: 'cost',
      header: 'Cost rate',
      align: 'right',
      cell: (it) => (
        <div>
          {formatINR(it.cost_rate)}
          {it.analysis.length ? <div className="text-[11px] text-success">built up from {it.analysis.length}</div> : <div className="text-[11px] text-muted-foreground">typed</div>}
        </div>
      ),
    },
    { id: 'quoted', header: 'We ask', align: 'right', cell: (it) => <span className="font-semibold">{formatINR(it.quoted_rate)}</span> },
    { id: 'amount', header: 'Amount', hideBelow: 'md', align: 'right', cell: (it) => formatINR(it.quoted_amount) },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (it) =>
        locked ? null : (
          <div className="flex justify-end gap-1.5">
            <Button size="sm" variant="outline" onClick={() => setRating(it)}>Rate</Button>
            <Button size="icon-sm" variant="ghost" aria-label={`Remove ${it.item_no}`} onClick={() => setRemoving(it)}><X /></Button>
          </div>
        ),
    },
  ]

  const buttons: { a: Act; label: string; primary?: boolean; need: string }[] = [
    { a: 'submit', label: 'Submit the price', primary: true, need: 'SUBMIT' },
    { a: 'win', label: 'We won it', primary: true, need: 'WIN' },
    { a: 'lose', label: 'We lost it', need: 'LOSE' },
    { a: 'reopen', label: 'Reopen', need: 'REOPEN' },
    { a: 'withdraw', label: 'Withdraw', need: 'WITHDRAW' },
  ]
  const tone = ESTIMATE_TONE[e.status] ?? 'neutral'

  return (
    <>
      <Link to="/clients/estimates" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Tenders & Estimates</Link>
      <PageHeader
        eyebrow={e.number}
        title={e.title}
        description={[e.customer_name, e.tender_reference].filter(Boolean).join(' · ') || undefined}
        actions={
          <>
            <Badge tone={tone}>{e.status.charAt(0) + e.status.slice(1).toLowerCase()}</Badge>
            {e.work_order && <span className="text-sm">became <strong>{e.work_order}</strong></span>}
            <Button variant="outline" asChild><a href={`/api/estimates/${e.id}/export.xlsx`}><Download /> Excel</a></Button>
            {buttons.filter((b) => e.actions.includes(b.need)).map((b) => (
              <Button key={b.a} variant={b.primary ? 'primary' : 'outline'} loading={act.isPending && act.variables?.action === b.a} onClick={() => (b.a === 'win' || b.a === 'lose' ? setAsking(b.a) : act.mutate({ action: b.a }))}>{b.label}</Button>
            ))}
          </>
        }
      />

      <div className="mb-6 grid max-w-md grid-cols-2 gap-4">
        <Field label="Overhead %" htmlFor="es-oh" hint="On cost.">
          <NumField id="es-oh" disabled={locked} value={e.overhead_percent} onValue={() => undefined} onBlur={(ev) => Number(ev.currentTarget.value) !== e.overhead_percent && head.mutate({ overhead_percent: Number(ev.currentTarget.value) || 0, profit_percent: e.profit_percent })} />
        </Field>
        <Field label="Profit %" htmlFor="es-pf" hint="On the result.">
          <NumField id="es-pf" disabled={locked} value={e.profit_percent} onValue={() => undefined} onBlur={(ev) => Number(ev.currentTarget.value) !== e.profit_percent && head.mutate({ overhead_percent: e.overhead_percent, profit_percent: Number(ev.currentTarget.value) || 0 })} />
        </Field>
      </div>

      <StatGrid className="xl:grid-cols-3">
        <Stat label="It will cost" value={formatINR(e.cost_total)} />
        <Stat label="We ask" value={formatINR(e.quoted_total)} />
        <Stat label="Margin" value={formatINR(e.margin_amount)} sub={`${e.margin_percent}%`} tone={e.margin_amount < 0 ? 'danger' : undefined} />
      </StatGrid>

      <DataTable label="Estimate items" rows={e.items} columns={columns} rowKey={(it) => it.id} empty="No items yet. Add the BOQ items from the tender." />

      {!locked && (
        <div className="mt-4 grid items-end gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-[5rem_1fr_6rem_8rem_8rem_auto]">
          <Field label="No." htmlFor="ei-no"><Input id="ei-no" value={item.item_no} onChange={(ev) => setItem((s) => ({ ...s, item_no: ev.target.value }))} /></Field>
          <Field label="Item" htmlFor="ei-desc"><Input id="ei-desc" value={item.description} onChange={(ev) => setItem((s) => ({ ...s, description: ev.target.value }))} placeholder="Describe the item" /></Field>
          <Field label="Unit" htmlFor="ei-uom"><Input id="ei-uom" value={item.uom} onChange={(ev) => setItem((s) => ({ ...s, uom: ev.target.value }))} /></Field>
          <Field label="Quantity" htmlFor="ei-qty"><NumField id="ei-qty" value={item.quantity} onValue={(n) => setItem((s) => ({ ...s, quantity: n }))} /></Field>
          <Field label="Cost rate" htmlFor="ei-rate"><NumField id="ei-rate" value={item.cost_rate} onValue={(n) => setItem((s) => ({ ...s, cost_rate: n }))} /></Field>
          <Button loading={add.isPending} disabled={!item.description.trim()} onClick={() => add.mutate()}><Plus /> Add</Button>
        </div>
      )}

      <RateAnalysisModal estimate={e} item={rating} onClose={() => setRating(null)} />
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title="Remove this item?" description="It goes, with its rate build-up." confirmLabel="Remove it" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing) }} />
      <ConfirmDialog open={asking === 'win'} onOpenChange={(o) => !o && setAsking(null)} title="Mark this tender as won?" description="A work order will be drawn up from it, line for line." confirmLabel="We won it" loading={act.isPending} onConfirm={() => act.mutate({ action: 'win' })} />
      <ConfirmDialog open={asking === 'lose'} onOpenChange={(o) => !o && setAsking(null)} title="Mark this tender as lost?" confirmLabel="We lost it" tone="danger" reason={{ label: 'Why did we lose it? (L1 price, spec, timing...)' }} loading={act.isPending} onConfirm={(reason) => act.mutate({ action: 'lose', reason })} />
    </>
  )
}
