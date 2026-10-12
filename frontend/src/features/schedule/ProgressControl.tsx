import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'
import { Button } from '@/components/ui'
import { schKeys, setProgress } from '@/api/schedule'
import { useAction } from '@/lib/mutate'

/**
 * Progress changed where it is shown. Drag the slider (or tap +10 / Done) and save: the report is dated and kept with
 * who made it, as ever. `compact` is two buttons for a tight row.
 */
export function ProgressControl({ id, percent, compact, updatedOn, updatedBy }: { id: number; percent: number; compact?: boolean; updatedOn?: string; updatedBy?: string }) {
  const [value, setValue] = useState(percent)
  useEffect(() => setValue(percent), [percent])
  const save = useAction((pct: number) => setProgress(id, pct), { invalidate: [schKeys.all], success: 'Progress recorded' })
  const changed = Math.round(value) !== Math.round(percent)

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
