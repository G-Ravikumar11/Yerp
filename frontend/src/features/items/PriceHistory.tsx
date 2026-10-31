import { useState } from 'react'
import { Trash2 } from 'lucide-react'
import { Button, Field, Input } from '@/components/ui'
import { addRateContract, priceKeys, removeRateContract, setRateAlert, usePriceHistory, usePurchaseControls, type PricePoint } from '@/api/poControls'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

/** The prices an item was bought at, as a line over time: rising, falling or flat at a glance. */
export function PriceTrend({ points, height = 56 }: { points: PricePoint[]; height?: number }) {
  if (points.length < 2) return null
  const rates = points.map((p) => p.rate)
  const lo = Math.min(...rates), hi = Math.max(...rates)
  const w = 240
  const x = (i: number) => (i / (points.length - 1)) * (w - 8) + 4
  const y = (r: number) => (hi === lo ? height / 2 : height - 4 - ((r - lo) / (hi - lo)) * (height - 8))
  const first = rates[0], last = rates[rates.length - 1]
  const change = first ? ((last - first) / first) * 100 : 0
  return (
    <figure className="m-0 flex items-center gap-3" aria-label={`Price trend: ${formatINR(first)} to ${formatINR(last)}`}>
      <svg width={w} height={height} viewBox={`0 0 ${w} ${height}`} role="img" aria-hidden="true" className="shrink-0 overflow-visible">
        <polyline fill="none" stroke="var(--primary)" strokeWidth="2" points={points.map((p, i) => `${x(i)},${y(p.rate)}`).join(' ')} />
        {points.map((p, i) => <circle key={i} cx={x(i)} cy={y(p.rate)} r="2.5" fill="var(--card)" stroke="var(--primary)" strokeWidth="1.5"><title>{`${formatDate(p.on)} ${formatINR(p.rate)} - ${p.supplier}, ${p.po}`}</title></circle>)}
      </svg>
      <figcaption className="text-xs text-muted-foreground">
        {formatINR(first)} → <strong className="text-foreground">{formatINR(last)}</strong>
        <div className={change > 0.05 ? 'text-danger' : change < -0.05 ? 'text-success' : ''}>{change > 0 ? '+' : ''}{change.toFixed(1)}% over {points.length} orders</div>
      </figcaption>
    </figure>
  )
}

/** On the item: every price it was bought at, the last per supplier, its rate contracts, and how far over is flagged. */
export function PriceHistorySection({ itemCode, manage }: { itemCode: string; manage: boolean }) {
  const q = usePriceHistory(itemCode)
  const ctl = usePurchaseControls()
  const d = q.data
  const [c, setC] = useState({ supplier_name: '', rate: '', valid_from: '', valid_to: '', reference: '' })
  const [pct, setPct] = useState('')
  const inv = { invalidate: [priceKeys.all] }
  const add = useAction(() => addRateContract({ item_code: itemCode, supplier_name: c.supplier_name.trim(), rate: Number(c.rate), valid_from: c.valid_from, valid_to: c.valid_to, reference: c.reference }),
    { ...inv, success: (r) => r.message, onSuccess: () => setC({ supplier_name: '', rate: '', valid_from: '', valid_to: '', reference: '' }) })
  const drop = useAction((id: number) => removeRateContract(id), inv)
  const alert = useAction(() => setRateAlert(Number(pct)), { ...inv, success: 'Rate alert saved', onSuccess: () => setPct('') })
  return (
    <section aria-labelledby="d-prices">
      <h3 id="d-prices" className="mb-2 border-b pb-1 text-sm font-semibold">Price history</h3>
      {!d ? <p className="text-sm text-muted-foreground">Loading...</p> : d.points.length === 0 ? (
        <p className="text-sm text-muted-foreground">Not bought on an approved order yet.</p>
      ) : (
        <div className="grid gap-3 text-sm">
          <PriceTrend points={d.points} />
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Last price, by supplier</p>
            <ul className="grid gap-0.5">{d.last_by_supplier.map((p) => <li key={p.supplier}><strong>{formatINR(p.rate)}</strong> {p.supplier} <span className="text-xs text-muted-foreground">({p.po}, {formatDate(p.on)})</span></li>)}</ul>
          </div>
        </div>
      )}
      <div className="mt-3 grid gap-2 text-sm">
        <p className="text-xs font-medium text-muted-foreground">Rate contracts</p>
        {(d?.contracts ?? []).length === 0 && <p className="text-muted-foreground">None.</p>}
        <ul className="grid gap-0.5">{(d?.contracts ?? []).map((k) => (
          <li key={k.id} className="flex items-center gap-2"><strong>{formatINR(k.rate)}</strong> {k.supplier_name}
            <span className="text-xs text-muted-foreground">{formatDate(k.valid_from)}{k.valid_to ? ` to ${formatDate(k.valid_to)}` : ' onwards'}{k.reference ? ` · ${k.reference}` : ''}</span>
            {manage && <button type="button" aria-label={`Remove the rate contract with ${k.supplier_name}`} className="ml-auto text-muted-foreground hover:text-danger" onClick={() => drop.mutate(k.id)}><Trash2 className="size-4" /></button>}
          </li>))}</ul>
        {manage && (
          <form className="grid gap-2 sm:grid-cols-5" onSubmit={(e) => { e.preventDefault(); if (c.supplier_name.trim() && Number(c.rate) > 0) add.mutate() }}>
            <Field label="Supplier" htmlFor="rc-sup" className="sm:col-span-2"><Input id="rc-sup" value={c.supplier_name} onChange={(e) => setC({ ...c, supplier_name: e.target.value })} /></Field>
            <Field label="Agreed rate" htmlFor="rc-rate"><Input id="rc-rate" inputMode="decimal" value={c.rate} onChange={(e) => setC({ ...c, rate: e.target.value })} /></Field>
            <Field label="From" htmlFor="rc-from"><Input id="rc-from" type="date" value={c.valid_from} onChange={(e) => setC({ ...c, valid_from: e.target.value })} /></Field>
            <Field label="To" htmlFor="rc-to"><Input id="rc-to" type="date" value={c.valid_to} onChange={(e) => setC({ ...c, valid_to: e.target.value })} /></Field>
            <div className="flex items-center gap-2 sm:col-span-5">
              {add.error && <p role="alert" className="text-[13px] text-danger">{add.error.message}</p>}
              <Button type="submit" size="sm" variant="outline" className="ml-auto" loading={add.isPending} disabled={!c.supplier_name.trim() || !(Number(c.rate) > 0)}>Add rate contract</Button>
            </div>
          </form>
        )}
        {manage && (
          <form className="flex flex-wrap items-end gap-2 border-t border-border pt-2" onSubmit={(e) => { e.preventDefault(); if (pct !== '') alert.mutate() }}>
            <Field label={`Flag an order rate this % over the last price (now ${ctl.data?.rate_alert_pct ?? 10}%, for every item)`} htmlFor="rc-pct" className="flex-1">
              <Input id="rc-pct" inputMode="decimal" value={pct} onChange={(e) => setPct(e.target.value)} placeholder={String(ctl.data?.rate_alert_pct ?? 10)} />
            </Field>
            <Button type="submit" size="sm" variant="outline" loading={alert.isPending} disabled={pct === ''}>Save</Button>
          </form>
        )}
      </div>
    </section>
  )
}
