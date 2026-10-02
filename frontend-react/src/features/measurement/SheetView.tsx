import { Fragment } from 'react'
import { Badge } from '@/components/ui'
import type { MbDimension, MbEntry, MbLine } from '@/api/mb'
import { formatDate, formatQty } from '@/lib/format'
import { cn } from '@/lib/utils'

const HELD = /^held back/i

/** What one line comes to: the figures multiplied, a deduction taken away. */
const lineQty = (d: MbDimension) => {
  if (d.is_heading) return null
  const parts = [d.nos, d.nom, d.length, d.breadth, d.depth].filter((v): v is number => v !== null && v !== undefined)
  if (!parts.length) return d.quantity ?? null
  const q = parts.reduce((a, v) => a * v, 1)
  return d.deduct ? -Math.abs(q) : q
}
const oneBlock = (e: MbEntry) => e.dimensions.reduce((n, d) => n + (lineQty(d) ?? 0), 0)
/** The part of an entry held back for finishes, added up from its held-back line. */
const heldOf = (e: MbEntry) => e.dimensions.filter((d) => HELD.test(d.particulars)).reduce((n, d) => n + Math.abs(lineQty(d) ?? 0), 0) * (e.multiplier || 1)
const num = (v: number | null | undefined) => (v === null || v === undefined ? '' : formatQty(v))

const COLS = 8
const sum = (list: MbEntry[], f: (e: MbEntry) => number) => list.reduce((n, e) => n + f(e), 0)

/** The footer under a group of blocks that share one hold-back: before, held, and to be paid. */
function GroupFooter({ group }: { group: MbEntry[] }) {
  const paid = sum(group, (e) => e.quantity)
  const held = sum(group, heldOf)
  if (held <= 0) return null
  return (
    <>
      <tr className="border-t border-border bg-muted/50">
        <td className="px-3 py-1 pl-9" colSpan={COLS - 1}>Total quantity, before holding back</td>
        <td className="tabular px-3 py-1 text-right">{formatQty(paid + held)}</td>
      </tr>
      <tr className="bg-muted/50">
        <td className="px-3 py-1 pl-9" colSpan={COLS - 1}>Held back for finishes and handing over</td>
        <td className="tabular px-3 py-1 text-right text-danger">−{formatQty(held)}</td>
      </tr>
      <tr className="bg-muted/50 font-semibold">
        <td className="px-3 py-1 pl-9" colSpan={COLS - 1}>Total quantity to be paid</td>
        <td className="tabular px-3 py-1 text-right">{formatQty(paid)}</td>
      </tr>
    </>
  )
}

/** One entry: its lettered heading, its lines as the site wrote them, and its totals. */
function Block({ e, uom, groupEnd, group }: { e: MbEntry; uom: string; groupEnd: boolean; group: MbEntry[] }) {
  // An entry written as a total, with no dimensions, is one line of its own.
  const measured = e.dimensions.some((d) => !d.is_heading)
  const one = measured ? oneBlock(e) : e.quantity / (e.multiplier || 1)
  return (
    <>
      <tr className="border-t border-border">
        <td colSpan={COLS} className="px-3 pb-1 pt-2.5 font-medium">
          <span className="mr-2 inline-block min-w-5 text-muted-foreground">{e.block_label}</span>
          {e.location || 'Measured'}
          <span className="ml-3 text-xs font-normal text-muted-foreground">{formatDate(e.measured_on)}</span>
          {e.billed && <Badge tone="info" className="ml-2">Billed</Badge>}
        </td>
      </tr>
      {!measured && (
        <tr>
          <td className="px-3 py-0.5 pl-9 text-muted-foreground">Measured as a total</td>
          <td className="px-2 py-0.5 text-muted-foreground">{uom}</td>
          <td colSpan={5} />
          <td className="tabular px-3 py-0.5 text-right">{formatQty(one)}</td>
        </tr>
      )}
      {e.dimensions.map((d, j) => {
        const q = lineQty(d)
        const held = HELD.test(d.particulars)
        return (
          <tr key={j} className={cn(held && 'bg-warning-soft/60')}>
            <td className={cn('px-3 py-0.5 pl-9', d.is_heading && 'font-semibold')}>{d.particulars}</td>
            <td className="px-2 py-0.5 text-muted-foreground">{d.is_heading ? '' : uom}</td>
            <td className="tabular px-2 py-0.5 text-right">{held ? '' : num(d.nos)}</td>
            <td className="tabular px-2 py-0.5 text-right">{num(d.nom)}</td>
            <td className="tabular px-2 py-0.5 text-right">{num(d.length)}</td>
            <td className="tabular px-2 py-0.5 text-right">{num(d.breadth)}</td>
            <td className="tabular px-2 py-0.5 text-right">{num(d.depth)}</td>
            <td className={cn('tabular px-3 py-0.5 text-right', q !== null && q < 0 && 'text-danger')}>{q === null ? '' : formatQty(q)}</td>
          </tr>
        )
      })}
      <tr className="border-t border-border/60 font-medium">
        <td className="px-3 py-1 pl-9" colSpan={COLS - 1}>Total quantity for one block</td>
        <td className="tabular px-3 py-1 text-right">{formatQty(one)}</td>
      </tr>
      {e.multiplier !== 1 && (
        <tr className="font-medium">
          <td className="px-3 py-1 pl-9" colSpan={COLS - 1}>Total quantity for {e.multiplier} blocks{heldOf(e) > 0 ? ' (after the hold-back)' : ''}</td>
          <td className="tabular px-3 py-1 text-right">{formatQty(e.quantity)}</td>
        </tr>
      )}
      {groupEnd && <GroupFooter group={group} />}
    </>
  )
}

/**
 * The measurement book laid out as the site keeps it in Excel: each section, its lettered blocks with their
 * lines and totals, the part held back under a group of blocks and what is left to pay, and a grand total.
 */
export function SheetView({ entries, byItem }: { entries: MbEntry[]; byItem: Map<number, MbLine> }) {
  if (!entries.length) return <p className="py-10 text-center text-sm text-muted-foreground">Nothing measured yet.</p>
  const chrono = [...entries].sort((a, b) => a.id - b.id)
  const sectionOf = (e: MbEntry) => e.section || (byItem.get(e.item_id) ? `${byItem.get(e.item_id)?.activity_no ?? ''} ${byItem.get(e.item_id)?.description ?? ''}`.trim() : 'Measured')
  const sections: { name: string; entries: MbEntry[] }[] = []
  for (const e of chrono) {
    const name = sectionOf(e)
    const last = sections[sections.length - 1]
    if (last && last.name === name) last.entries.push(e)
    else sections.push({ name, entries: [e] })
  }
  const grandHeld = sum(chrono, heldOf)
  return (
    <div aria-label="Measurement sheet" className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-[56rem] border-collapse text-[13px]">
        <thead className="bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2">Description</th>
            <th className="px-2 py-2">UoM</th>
            <th className="px-2 py-2 text-right">No&apos;s</th>
            <th className="px-2 py-2 text-right">NoM</th>
            <th className="px-2 py-2 text-right">Length</th>
            <th className="px-2 py-2 text-right">Width</th>
            <th className="px-2 py-2 text-right">Height</th>
            <th className="px-3 py-2 text-right">Total quantity</th>
          </tr>
        </thead>
        <tbody>
          {sections.map((sec, si) => (
            <Fragment key={si}>
              <tr className="bg-primary-soft">
                <td colSpan={COLS} className="px-3 py-2 text-[13.5px] font-semibold">{sec.name}</td>
              </tr>
              {sec.entries.map((e, i) => {
                const next = sec.entries[i + 1]
                const groupEnd = !!e.group_ref && (!next || next.group_ref !== e.group_ref)
                return <Block key={e.id} e={e} uom={byItem.get(e.item_id)?.uom ?? ''} groupEnd={groupEnd} group={sec.entries.filter((x) => x.group_ref === e.group_ref)} />
              })}
              <tr className="border-t-2 border-border bg-surface font-semibold">
                <td colSpan={COLS - 1} className="px-3 py-2">Total for this section{sec.entries.length > 1 ? ` (${sec.entries.length} entries)` : ''}</td>
                <td className="tabular px-3 py-2 text-right">{formatQty(sum(sec.entries, (e) => e.quantity))}</td>
              </tr>
            </Fragment>
          ))}
          <tr className="border-t-2 border-border bg-primary-soft text-[14px] font-semibold">
            <td colSpan={COLS - 1} className="px-3 py-2.5">Total quantity to be paid{grandHeld > 0 ? ` (after ${formatQty(grandHeld)} held back)` : ''}</td>
            <td className="tabular px-3 py-2.5 text-right">{formatQty(sum(chrono, (e) => e.quantity))}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}
