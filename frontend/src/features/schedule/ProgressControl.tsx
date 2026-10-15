import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'
import { Button } from '@/components/ui'
import { schKeys, setProgress } from '@/api/schedule'
import { useAction } from '@/lib/mutate'

/**
 * Progress changed where it is shown. Drag the slider (or tap +10 / Done) and save: the report is dated and kept with
 * who made it, as ever. `compact` is two buttons for a tight row. An activity with a quantity (500 cum from the BOQ) is
 * recorded as how much is done so far, and its % is that over the quantity.
 */
export function ProgressControl({ id, percent, compact, updatedOn, updatedBy, quantity = 0, uom = '', qtyDone = 0 }: {
  id: number; percent: number; compact?: boolean; updatedOn?: string; updatedBy?: string; quantity?: number; uom?: string; qtyDone?: number
}) {
  const [value, setValue] = useState(percent)
  useEffect(() => setValue(percent), [percent])
  const save = useAction((pct: number) => setProgress(id, pct, quantity > 0 ? Math.round(pct * quantity) / 100 : undefined), { invalidate: [schKeys.all], success: 'Progress recorded' })
  const changed = Math.round(value) !== Math.round(percent)
  // keyed by what is saved, so a new figure from the server starts it afresh
  if (quantity > 0 && !compact) return <QuantityDone key={qtyDone} id={id} quantity={quantity} uom={uom} qtyDone={qtyDone} updatedOn={updatedOn} updatedBy={updatedBy} />

  if (compact) {
    return (
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="outline" disabled={percent >= 100 || save.isPending} onClick={() => save.mutate(Math.min(100, Math.round(percent) + 10))}>+10%</Button>
        <Button size="sm" variant="outline" disabled={percent >= 100 || save.isPending} onClick={() => save.mutate(100)}>Done</Button>
      </div>
    )
  }
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 border-t border-border pt-1.5">
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={Math.round(value)}
        onChange={(e) => setValue(Number(e.target.value))}
        aria-label="Set how much is done"
        className="h-2 min-w-32 flex-1 cursor-pointer accent-[var(--primary)]"
      />
      <span className="w-10 text-right text-xs tabular text-muted-foreground">{Math.round(value)}%</span>
      <Button size="sm" disabled={!changed} loading={save.isPending} onClick={() => save.mutate(Math.round(value))}><Check /> Save</Button>
      <Button size="sm" variant="outline" disabled={percent >= 100 || save.isPending} onClick={() => save.mutate(Math.min(100, Math.round(percent) + 10))}>+10%</Button>
      <Button size="sm" variant="outline" disabled={percent >= 100 || save.isPending} onClick={() => save.mutate(100)}>Done</Button>
      {updatedOn && <span className="w-full text-[11px] text-muted-foreground">Last updated {updatedOn}{updatedBy ? ` by ${updatedBy}` : ''}</span>}
    </div>
  )
}

const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(3).replace(/\.?0+$/, ''))

/** How much of the quantity is done so far, as the site measures it: 320 of 500 cum is 64%. */
function QuantityDone({ id, quantity, uom, qtyDone, updatedOn, updatedBy }: { id: number; quantity: number; uom: string; qtyDone: number; updatedOn?: string; updatedBy?: string }) {
  const [value, setValue] = useState(() => fmt(qtyDone))
  const save = useAction((q: number) => setProgress(id, Math.min(100, (q / quantity) * 100), q), { invalidate: [schKeys.all], success: 'Progress recorded' })
  const q = Number(value)
  const bad = value.trim() === '' || Number.isNaN(q) || q < 0
  const over = !bad && q > quantity
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 border-t border-border pt-1.5">
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
        Done so far
        <input inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} aria-label={`Quantity done so far, in ${uom || 'units'}`}
          className="h-8 w-24 rounded-md border border-input bg-background px-2 text-right text-sm tabular-nums text-foreground" />
        <span>of {fmt(quantity)} {uom}{!bad ? ` = ${Math.round(Math.min(100, (q / quantity) * 100))}%` : ''}</span>
      </label>
      <Button size="sm" disabled={bad || q === qtyDone} loading={save.isPending} onClick={() => save.mutate(q)}><Check /> Save</Button>
      <Button size="sm" variant="outline" disabled={qtyDone >= quantity || save.isPending} onClick={() => save.mutate(quantity)}>All done</Button>
      {over && <span className="w-full text-[11px] text-warning">More than the {fmt(quantity)} {uom} planned: it counts as 100%.</span>}
      {updatedOn && <span className="w-full text-[11px] text-muted-foreground">Last updated {updatedOn}{updatedBy ? ` by ${updatedBy}` : ''}</span>}
    </div>
  )
}
