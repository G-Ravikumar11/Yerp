import { useMemo, useState } from 'react'
import { Button, Modal, Skeleton } from '@/components/ui'
import { pullBoqLines, useAvailable, useBoqs } from '@/api/boq'
import { useAction } from '@/lib/mutate'
import { formatQty } from '@/lib/format'
import { cn } from '@/lib/utils'
import { toast } from '@/stores/toast'

interface Pick {
  quantity: string
  rate: string
}

/**
 * Lines of the project's BOQ, taken into this order's schedule: tick the ones this gang is to do, say how much
 * of each and at what gang rate. Each keeps its link to the BOQ line, so what is given out can be added up
 * against what the client's BOQ allows.
 */
export function BoqPicker({ orderId, jobId, open, onOpenChange, onAdd }: { orderId: number; jobId: number; open: boolean; onOpenChange: (o: boolean) => void; onAdd: (lines: Record<string, unknown>[]) => void }) {
  const boqs = useBoqs()
  const boq = (boqs.data?.boqs ?? []).find((b) => b.job_id === jobId)
  const avail = useAvailable(open && boq ? boq.id : 0)
  const [picks, setPicks] = useState<Record<string, Pick>>({})
  const lines = useMemo(() => avail.data?.lines ?? [], [avail.data])

  const ticked = Object.entries(picks)
  const incomplete = ticked.some(([, p]) => !(Number(p.quantity) > 0) || !(Number(p.rate) > 0))

  const add = useAction(
    () => pullBoqLines(orderId, ticked.map(([key, p]) => ({ key, quantity: Number(p.quantity), rate: Number(p.rate) }))),
    {
      onSuccess: (r) => {
        onAdd(r.lines)
        r.warnings.forEach((w) => toast.info(w))
        setPicks({})
        onOpenChange(false)
      },
    },
  )

  const toggle = (key: string, left: number, on: boolean) =>
    setPicks((s) => {
      const next = { ...s }
      if (on) next[key] = { quantity: String(left || ''), rate: '' }
      else delete next[key]
      return next
    })
  const set = (key: string, field: keyof Pick, value: string) => setPicks((s) => ({ ...s, [key]: { ...s[key], [field]: value } }))

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title="Take lines from the project BOQ"
      description={boq ? `${boq.number} ${boq.revision}. The quantity offered is what is still to be given to a gang; the gang rate is yours to type.` : undefined}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={add.isPending} disabled={!ticked.length || incomplete} onClick={() => add.mutate()}>
            Add {ticked.length || ''} {ticked.length === 1 ? 'line' : 'lines'} to the schedule
          </Button>
        </>
      }
    >
      {boqs.isPending || (boq && avail.isPending) ? (
        <Skeleton className="h-48 w-full" />
      ) : !boq ? (
        <p className="py-8 text-center text-sm text-muted-foreground">This project has no BOQ yet. Start one under Projects, BOQ.</p>
      ) : (
        <div className="max-h-[26rem] overflow-y-auto rounded-lg border border-border">
          <table aria-label="Lines of the project BOQ" className="w-full text-[13px]">
            <thead className="sticky top-0 bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="w-10 px-3 py-2" />
                <th className="px-2 py-2">S.No</th>
                <th className="px-2 py-2">Description</th>
                <th className="px-2 py-2 text-right">BOQ qty</th>
                <th className="px-2 py-2 text-right">Left to give</th>
                <th className="w-28 px-2 py-2 text-right">Quantity</th>
                <th className="w-28 px-2 py-2 text-right">Gang rate</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) =>
                l.kind === 'section' ? (
                  <tr key={i} className="border-t border-border bg-surface/60">
                    <td colSpan={7} className="px-3 py-1.5 font-semibold">
                      {l.sno} {l.description}
                    </td>
                  </tr>
                ) : (
                  <tr key={l.key} className="border-t border-border">
                    <td className="px-3 py-1.5">
                      <input type="checkbox" aria-label={`Take ${l.sno || l.description}`} checked={!!picks[l.key!]} onChange={(e) => toggle(l.key!, l.left ?? 0, e.target.checked)} />
                    </td>
                    <td className="px-2 py-1.5 font-mono text-xs">{l.sno}</td>
                    <td className="max-w-xs truncate px-2 py-1.5" title={l.description}>{l.description}</td>
                    <td className="tabular px-2 py-1.5 text-right">{formatQty(l.quantity ?? 0)} {l.uom}</td>
                    <td className={cn('tabular px-2 py-1.5 text-right', !l.left && 'text-muted-foreground')}>{formatQty(l.left ?? 0)}</td>
                    <td className="px-2 py-1">
                      {picks[l.key!] && <input aria-label={`Quantity of ${l.sno}`} inputMode="decimal" className="h-8 w-full rounded-md border border-input bg-background px-2 text-right" value={picks[l.key!].quantity} onChange={(e) => set(l.key!, 'quantity', e.target.value)} />}
                    </td>
                    <td className="px-2 py-1">
                      {picks[l.key!] && <input aria-label={`Gang rate of ${l.sno}`} inputMode="decimal" placeholder="Rs / unit" className="h-8 w-full rounded-md border border-input bg-background px-2 text-right" value={picks[l.key!].rate} onChange={(e) => set(l.key!, 'rate', e.target.value)} />}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
