import { useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { DataGrid } from '@/components/grid'
import { Button, Field, Input, NumField } from '@/components/ui'
import { batchUrl, mbKeys, type MbLine } from '@/api/mb'
import { blankDim, dimTotal, type DimLine } from '@/lib/measure'
import { formatQty, today } from '@/lib/format'
import { useAction } from '@/lib/mutate'
import { sendOrQueue } from '@/stores/offline'
import { toast } from '@/stores/toast'
import { dimColumns } from './dimensions'

/** One block read from the sheet, loaded into the grid to be checked. */
export interface LoadedBlock {
  key: string
  location: string
  multiplier: number
  dims: DimLine[]
  /** Blocks that share one hold in the sheet carry the same group. */
  group: string
  /** The sheet's section it came from: "II Internal Painting Work". */
  section: string
  letter: string
}

/** What the sheet holds back on a group of blocks: its own words, and the share. */
export interface LoadedHold {
  reason: string
  percent: number
}

export interface Loaded {
  blocks: LoadedBlock[]
  holds: Record<string, LoadedHold>
  source: string
}

const round3 = (n: number) => Math.round(n * 1000) / 1000
const blockTotal = (b: LoadedBlock) => round3(dimTotal(b.dims) * (b.multiplier || 1))
const sendable = (dims: DimLine[]) =>
  dims
    .filter((d) => d.particulars.trim() || [d.nos, d.nom, d.length, d.breadth, d.depth].some((v) => v !== null))
    .map((d) => ({ particulars: d.particulars, nos: d.nos, nom: d.nom, length: d.length, breadth: d.breadth, depth: d.depth, deduct: d.deduct, is_heading: d.heading }))

/**
 * The blocks ticked in the sheet, each in the grid as the sheet wrote it - its lines in the No's, NoM, L, B, H
 * columns, its blocks-alike count, its total - and under each group of blocks what the sheet holds back on them.
 * Every figure can be changed. Nothing is saved until Record, and then all of it goes in or none of it does.
 */
export function SheetBlocks({ orderId, line, loaded, onDone, onDiscard }: { orderId: number; line: MbLine; loaded: Loaded; onDone: () => void; onDiscard: () => void }) {
  const [blocks, setBlocks] = useState<LoadedBlock[]>(loaded.blocks)
  const [holds, setHolds] = useState<Record<string, LoadedHold>>(loaded.holds)
  const [on, setOn] = useState(today())
  const [ref, setRef] = useState(loaded.source)
  const [remarks, setRemarks] = useState('Imported from the measurement book')
  const [sameOk, setSameOk] = useState(false)
  const columns = useMemo(() => dimColumns, [])

  const groupTotal = (g: string) => round3(blocks.filter((b) => b.group === g).reduce((n, b) => n + blockTotal(b), 0))
  const heldOf = (g: string) => (holds[g] && holds[g].percent > 0 ? round3((groupTotal(g) * holds[g].percent) / 100) : 0)
  const groups = [...new Set(blocks.map((b) => b.group).filter((g) => g && holds[g]))]
  const measured = round3(blocks.reduce((n, b) => n + blockTotal(b), 0))
  const held = round3(groups.reduce((n, g) => n + heldOf(g), 0))
  const room = (line.max_quantity ?? Infinity) - (line.measured_to_date ?? 0)
  const over = measured > room + 0.0001
  // Different works of the sheet going onto one item of the order are asked about, not assumed.
  const works = [...new Set(blocks.map((b) => b.section.replace(/^\S+\s+/, '').trim().toLowerCase()).filter(Boolean))]
  const mixed = works.length > 1

  const update = (key: string, patch: Partial<LoadedBlock>) => setBlocks((list) => list.map((b) => (b.key === key ? { ...b, ...patch } : b)))

  const save = useAction(
    async () => {
      const body = {
        item_id: line.item_id,
        measured_on: on,
        mb_ref: ref,
        remarks,
        entries: blocks.map((b) => ({ location: b.location, multiplier: b.multiplier || 1, dimensions: sendable(b.dims), section: b.section, block_label: b.letter, group: b.group })),
        holds: groups.filter((g) => heldOf(g) > 0).map((g) => ({ group: g, quantity: heldOf(g), reason: holds[g].reason.trim() || `Held back - ${holds[g].percent}% held` })),
      }
      const sent = await sendOrQueue<{ message: string }>({ method: 'POST', url: batchUrl(orderId), body, label: `${blocks.length} blocks measured against ${line.activity_no}` })
      if (sent.queued) {
        toast.info('No connection - kept on this device and sent when it returns.')
        return { message: '' }
      }
      return sent.result
    },
    { invalidate: [mbKeys.all, ['subbills']], onSuccess: onDone },
  )

  return (
    <div aria-label="Blocks loaded from the sheet">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/40 bg-primary-soft px-3 py-2 text-[13px]">
        <span>
          <strong>{blocks.length}</strong> {blocks.length === 1 ? 'block' : 'blocks'} from the sheet, in the grid as the sheet wrote them. Check or change any figure - nothing is saved until you press Record.
        </span>
        <Button size="sm" variant="ghost" onClick={onDiscard}>
          Discard and type instead
        </Button>
      </div>

      <div className="flex flex-col gap-4">
        {blocks.map((b, i) => {
          const next = blocks[i + 1]
          const closesGroup = !!b.group && !!holds[b.group] && (!next || next.group !== b.group)
          const one = round3(dimTotal(b.dims))
          return (
            <div key={b.key}>
              <section aria-label={`Block ${i + 1}`} className="rounded-lg border border-border">
                <div className="flex flex-wrap items-end gap-3 border-b border-border bg-muted/40 px-3 py-2">
                  <span className="pb-2 font-mono text-xs text-muted-foreground">{b.letter || i + 1}</span>
                  <Field label="Where" htmlFor={`sb-where-${b.key}`} className="min-w-[14rem] flex-1">
                    <Input id={`sb-where-${b.key}`} value={b.location} onChange={(e) => update(b.key, { location: e.target.value })} />
                  </Field>
                  <Field label="Blocks alike" htmlFor={`sb-mult-${b.key}`} className="w-28">
                    <NumField id={`sb-mult-${b.key}`} value={b.multiplier} onValue={(n) => update(b.key, { multiplier: n > 0 ? n : 1 })} />
                  </Field>
                  <p className="pb-2 text-[13px] tabular">
                    {b.multiplier !== 1 && (
                      <span className="text-muted-foreground">
                        one block {formatQty(one)} × {b.multiplier} ={' '}
                      </span>
                    )}
                    <strong>{formatQty(blockTotal(b))}</strong> {line.uom}
                  </p>
                  <Button variant="ghost" size="icon-sm" className="mb-1 ml-auto" aria-label={`Leave out ${b.location || 'block ' + (i + 1)}`} onClick={() => setBlocks((list) => list.filter((x) => x.key !== b.key))}>
                    <X />
                  </Button>
                </div>
                <div className="p-2">
                  <DataGrid aria-label={`Lines of ${b.location || 'block ' + (i + 1)}`} columns={columns} rows={b.dims} onRowsChange={(rows) => update(b.key, { dims: rows })} newRow={blankDim} minRows={1} maxHeight={300} rowClassName={(r) => (r.heading ? 'font-semibold' : undefined)} />
                </div>
              </section>
              {closesGroup && (
                <div aria-label="What the sheet holds back" className="mt-2 grid gap-3 rounded-lg border border-warning/40 bg-warning-soft px-3 py-2.5 text-[13px] sm:grid-cols-[1fr_auto]">
                  <div className="grid gap-2">
                    <p>
                      Before holding back <strong className="tabular">{formatQty(groupTotal(b.group))}</strong> {line.uom}
                      {blocks.filter((x) => x.group === b.group).length > 1 && <span className="text-muted-foreground"> ({blocks.filter((x) => x.group === b.group).length} blocks)</span>}
                    </p>
                    <Field label="Why it is held" htmlFor={`sb-why-${b.group}`}>
                      <Input id={`sb-why-${b.group}`} value={holds[b.group].reason} onChange={(e) => setHolds((h) => ({ ...h, [b.group]: { ...h[b.group], reason: e.target.value } }))} />
                    </Field>
                  </div>
                  <div className="grid content-end gap-1 sm:min-w-[12rem]">
                    <Field label="Held (%)" htmlFor={`sb-pct-${b.group}`}>
                      <NumField id={`sb-pct-${b.group}`} value={holds[b.group].percent} onValue={(n) => setHolds((h) => ({ ...h, [b.group]: { ...h[b.group], percent: Math.max(0, Math.min(100, n)) } }))} />
                    </Field>
                    <p className="tabular">
                      Held <strong>{formatQty(heldOf(b.group))}</strong> · to be paid <strong>{formatQty(round3(groupTotal(b.group) - heldOf(b.group)))}</strong>
                    </p>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {mixed && (
        <label className="mt-4 flex items-start gap-2 rounded-lg border border-danger/40 bg-danger-soft p-3 text-[13px] text-danger">
          <input type="checkbox" aria-label="They are all this item" className="mt-0.5" checked={sameOk} onChange={(e) => setSameOk(e.target.checked)} />
          <span>
            These blocks come from {works.length} different works in the sheet ({works.slice(0, 3).join('; ')}). Tick only if they are all {line.description}, at its one rate.
          </span>
        </label>
      )}

      <div className="mt-5 grid gap-4 sm:grid-cols-3">
        <Field label="Measured on" htmlFor="sb-on">
          <Input id="sb-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
        </Field>
        <Field label="MB reference" htmlFor="sb-ref">
          <Input id="sb-ref" value={ref} onChange={(e) => setRef(e.target.value)} />
        </Field>
        <Field label="Remarks" htmlFor="sb-remarks">
          <Input id="sb-remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
        </Field>
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <div aria-label="What will be recorded" className="text-[13px]">
          <p className="tabular">
            Measured <strong>{formatQty(measured)}</strong> {line.uom}
            {held > 0 && (
              <>
                {' '}
                · held <strong>{formatQty(held)}</strong> · to be paid <strong>{formatQty(round3(measured - held))}</strong>
              </>
            )}
          </p>
          {Number.isFinite(room) && <p className={over ? 'text-danger' : 'text-muted-foreground'}>{over ? `That is more than the ${formatQty(Math.max(0, room))} still allowed on this item - amend the order or leave some out.` : `${formatQty(Math.max(0, room))} still allowed on this item.`}</p>}
        </div>
        <div className="flex items-center gap-2">
          {save.error && (
            <p role="alert" className="max-w-md text-right text-[13px] text-danger">
              {save.error.message}
            </p>
          )}
          <Button loading={save.isPending} disabled={!blocks.length || measured === 0 || (mixed && !sameOk)} onClick={() => save.mutate()}>
            Record {blocks.length} {blocks.length === 1 ? 'block' : 'blocks'}
          </Button>
        </div>
      </div>
    </div>
  )
}
