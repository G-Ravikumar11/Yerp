import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Skeleton } from '@/components/ui'
import { assetKeys, disposeAsset, methodText, saveBlock, useSchedule, type TaxBlock } from '@/api/assets'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { cn, formatINR } from '@/lib/utils'

/** Year by year: what an asset was worth at the start, what it lost, and what it is worth now. */
export function ScheduleModal({ assetId, onClose }: { assetId: number; onClose: () => void }) {
  const q = useSchedule(assetId)
  const d = q.data
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={d ? `${d.book.code} ${d.book.name} - ${methodText(d.book)}` : 'Years'}>
      {!d ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-[13px]">
            <thead><tr className="border-b border-border bg-surface text-left text-xs uppercase tracking-wide text-muted-foreground"><th className="px-3 py-2">Year</th><th className="px-3 py-2 text-right">Opening</th><th className="px-3 py-2 text-right">Depreciation</th><th className="px-3 py-2 text-right">Closing</th><th className="px-3 py-2 text-right">Accumulated</th></tr></thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.fy} className="border-b border-border last:border-0">
                  <td className="px-3 py-2">{r.fy}{r.days < 365 && <span className="text-xs text-muted-foreground"> ({r.days} days)</span>}</td>
                  <td className="tabular px-3 py-2 text-right">{formatINR(r.opening + r.added)}</td>
                  <td className="tabular px-3 py-2 text-right">{formatINR(r.depreciation)}</td>
                  <td className="tabular px-3 py-2 text-right font-semibold">{r.disposed ? <>sold {formatINR(r.disposal_value ?? 0)} <span className={cn('text-xs', (r.gain ?? 0) >= 0 ? 'text-success' : 'text-danger')}>({(r.gain ?? 0) >= 0 ? 'profit ' : 'loss '}{formatINR(Math.abs(r.gain ?? 0))})</span></> : formatINR(r.closing)}</td>
                  <td className="tabular px-3 py-2 text-right">{formatINR(r.accumulated ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}

/** Sold or scrapped: what it fetched, and the profit or loss against its book value. */
export function DisposeModal({ target, onClose }: { target: { id: number; title: string } | null; onClose: () => void }) {
  const [on, setOn] = useState(today())
  const [value, setValue] = useState(0)
  const [note, setNote] = useState('')
  const save = useAction(() => disposeAsset(target!.id, { disposed_on: on, disposal_value: value, note }), { invalidate: [assetKeys.all], onSuccess: onClose })
  return (
    <Modal open={!!target} onOpenChange={(o) => !o && onClose()} title={target ? `Sold or scrapped: ${target.title}` : 'Sold'}>
      <div className="grid gap-4">
        <Field label="On" htmlFor="ad-date"><Input id="ad-date" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Sale value" htmlFor="ad-value" hint="Nought if scrapped for nothing."><NumField id="ad-value" value={value} onValue={setValue} /></Field>
        <Field label="Note" htmlFor="ad-note"><Input id="ad-note" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => save.mutate()}>Record it</Button>
      </div>
    </Modal>
  )
}

/** An income-tax block: its rate, and where its written-down value opened. */
export function BlockModal({ block, onClose }: { block: TaxBlock | null; onClose: () => void }) {
  const [rate, setRate] = useState(block?.rate ?? 0)
  const [fy, setFy] = useState(block?.opening_fy ?? '')
  const [wdv, setWdv] = useState(block?.opening_wdv ?? 0)
  const save = useAction(() => saveBlock(block!.block_id, { rate, opening_fy: fy.trim(), opening_wdv: wdv }), { invalidate: [assetKeys.all], onSuccess: onClose })
  return (
    <Modal open={!!block} onOpenChange={(o) => !o && onClose()} title={block?.block ?? 'Block'}>
      <div className="grid gap-4">
        <Field label="Rate %" htmlFor="tb-rate"><NumField id="tb-rate" value={rate} onValue={setRate} /></Field>
        <Field label="Opening year" htmlFor="tb-fy" hint="e.g. 2024-25"><Input id="tb-fy" value={fy} onChange={(e) => setFy(e.target.value)} /></Field>
        <Field label="Written-down value at the start of it" htmlFor="tb-wdv"><NumField id="tb-wdv" value={wdv} onValue={setWdv} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </div>
    </Modal>
  )
}
