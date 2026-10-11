import { Pencil, Trash2 } from 'lucide-react'
import { Badge, Button, Modal } from '@/components/ui'
import type { MbEntry, MbLine } from '@/api/mb'
import { formatDate, formatQty } from '@/lib/format'
import { cn } from '@/lib/utils'
import { lineQty } from './SheetView'

const num = (v: number | null | undefined) => (v === null || v === undefined ? '' : formatQty(v))

/** What the lines of an entry come to for one block, as the sheet adds them up. */
export const entryOneBlock = (e: MbEntry) => e.dimensions.reduce((n, d) => n + (lineQty(d) ?? 0), 0)

/** A short reading of an entry's working: "3 × 5 × 2.5  − 1 × 2  × 2 blocks". */
export function calcSummary(e: MbEntry): string {
  const lines = e.dimensions.filter((d) => !d.is_heading)
  if (!lines.length) return ''
  const parts = lines.slice(0, 3).map((d) => {
    const figs = [d.nos, d.nom, d.length, d.breadth, d.depth].filter((v): v is number => v !== null && v !== undefined).map((v) => formatQty(v))
    return (d.deduct ? '− ' : '') + (figs.length ? figs.join(' × ') : formatQty(lineQty(d) ?? 0))
  })
  return parts.join('  ') + (lines.length > 3 ? `  … ${lines.length} lines` : '') + (e.multiplier !== 1 ? `  × ${e.multiplier} blocks` : '')
}

/** One entry opened out: every line with its figures and what it comes to, the blocks, and the total. */
export function EntryDetail({ entry, line, canChange, onEdit, onRemove, onClose }: { entry: MbEntry | null; line?: MbLine; canChange: boolean; onEdit: (e: MbEntry) => void; onRemove: (e: MbEntry) => void; onClose: () => void }) {
  const e = entry
  const measured = !!e?.dimensions.some((d) => !d.is_heading)
  const one = e ? (measured ? entryOneBlock(e) : e.quantity / (e.multiplier || 1)) : 0
  const title = e ? `${[line?.item_code, e.activity_no].filter(Boolean).join(' ')} ${line?.description ?? ''}` : 'Measurement'
  return (
    <Modal open={!!e} onOpenChange={(o) => !o && onClose()} size="xl" title={title} description={e ? [e.code, e.location, formatDate(e.measured_on), e.mb_ref].filter(Boolean).join(' · ') : undefined}>
      {e && (
        <div>
          {measured ? (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-[13px]">
                <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">Particulars</th>
                    {["No's", 'NoM', 'Length', 'Breadth', 'Depth'].map((h) => (
                      <th key={h} className="px-3 py-2 text-right font-medium">
                        {h}
                      </th>
                    ))}
                    <th className="px-3 py-2 text-right font-medium">Quantity</th>
                  </tr>
                </thead>
                <tbody>
                  {e.dimensions.map((d, i) => {
                    const q = lineQty(d)
                    return (
                      <tr key={i} className={cn('border-t border-border', d.is_heading && 'bg-muted/40 font-semibold')}>
                        <td className="px-3 py-1.5">
                          {d.particulars}
                          {d.deduct && <span className="ml-1.5 text-xs text-danger">deduct</span>}
                        </td>
                        {d.is_heading ? (
                          <td colSpan={6} />
                        ) : (
                          <>
                            <td className="tabular px-3 py-1.5 text-right">{num(d.nos)}</td>
                            <td className="tabular px-3 py-1.5 text-right">{num(d.nom)}</td>
                            <td className="tabular px-3 py-1.5 text-right">{num(d.length)}</td>
                            <td className="tabular px-3 py-1.5 text-right">{num(d.breadth)}</td>
                            <td className="tabular px-3 py-1.5 text-right">{num(d.depth)}</td>
                            <td className={cn('tabular px-3 py-1.5 text-right font-medium', (q ?? 0) < 0 && 'text-danger')}>{q === null ? '' : formatQty(q)}</td>
                          </>
                        )}
                      </tr>
                    )
                  })}
                  <tr className="border-t border-border bg-muted/40">
                    <td colSpan={6} className="px-3 py-1.5">
                      Total of the lines, for one block
                    </td>
                    <td className="tabular px-3 py-1.5 text-right font-medium">{formatQty(one)}</td>
                  </tr>
                  {e.multiplier !== 1 && (
                    <tr className="bg-muted/40">
                      <td colSpan={6} className="px-3 py-1.5">
                        Blocks built alike
                      </td>
                      <td className="tabular px-3 py-1.5 text-right">× {e.multiplier}</td>
                    </tr>
                  )}
                  <tr className="bg-muted/40 font-semibold">
                    <td colSpan={6} className="px-3 py-1.5">
                      Measured {line?.uom ? `(${line.uom})` : ''}
                    </td>
                    <td className="tabular px-3 py-1.5 text-right">{formatQty(e.quantity)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          ) : (
            <p className="rounded-lg border border-border bg-muted/40 px-3 py-3 text-sm">
              Measured as a total: <span className="font-semibold">{formatQty(e.quantity)}</span> {line?.uom}
              {e.multiplier !== 1 && (
                <>
                  {' '}
                  ({formatQty(one)} × {e.multiplier} blocks)
                </>
              )}
            </p>
          )}
          {e.remarks && <p className="mt-3 text-[13px] text-muted-foreground">{e.remarks}</p>}
          <p className="mt-3 text-xs text-muted-foreground">Recorded by {e.recorded_by_name}</p>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
            <div>{e.billed && <Badge tone="info">Billed</Badge>}</div>
            <div className="flex items-center gap-2">
              {canChange && (
                <Button variant="outline" onClick={() => onRemove(e)}>
                  <Trash2 /> Delete
                </Button>
              )}
              {canChange && (
                <Button onClick={() => onEdit(e)}>
                  <Pencil /> Change the calculation
                </Button>
              )}
              <Button variant="ghost" onClick={onClose}>
                Close
              </Button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  )
}
