import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, X } from 'lucide-react'
import { Button, Card, Input, Modal } from '@/components/ui'
import {
  itemSheetKeys, searchWorkItems, setLineWorks, workSuggestions, type ItemSheet, type SheetBoqLine, type SheetWork,
} from '@/api/itemSheet'
import { formatQty, plural } from '@/lib/format'
import { useAction } from '@/lib/mutate'

const lineLabel = (l: { item_no: string; description: string }) => `${l.item_no ? `${l.item_no} ` : ''}${l.description}`

/** The work item a BOQ line is, in a line: its code and name, and how many materials its norms have. */
export function WorkTag({ w }: { w: SheetWork }) {
  return (
    <span className="text-xs text-muted-foreground">
      Work <span className="font-mono">{w.code}</span> {w.name}
      {' · '}{w.norms ? plural(w.norms, 'material') + ' in its norms' : <span className="text-warning">no norms yet</span>}
      {w.from === 'sheet' && ' · chosen on the sheet'}
    </span>
  )
}

/** Choose which work item a BOQ line is: type to find one by code or name. Saved straight away; it does not change materials. */
export function WorkPicker({ job, line }: { job: number; line: SheetBoqLine }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [typed, setTyped] = useState('')
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { const t = setTimeout(() => setTyped(text.trim()), 200); return () => clearTimeout(t) }, [text])
  useEffect(() => {
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])
  const found = useQuery({ queryKey: ['item-sheet-works', job, typed], enabled: open, queryFn: () => searchWorkItems(job, typed) })
  const set = useAction((id: number | null) => setLineWorks(job, [{ boq_key: line.key, work_item_id: id }]), {
    invalidate: [itemSheetKeys.one(job)], success: (_r, id) => (id ? 'Work item set for the line.' : 'The line goes by its BOQ again.'),
    onSuccess: () => { setOpen(false); setText('') },
  })
  if (!open) return (
    <span className="flex flex-wrap items-center gap-2">
      <button type="button" className="text-xs font-medium text-primary hover:underline" onClick={() => setOpen(true)}>
        {line.work ? 'Change work item' : 'Which work item is this?'}
      </button>
      {line.work?.from === 'sheet' && <button type="button" className="text-xs text-muted-foreground hover:underline" onClick={() => set.mutate(null)}>Go by the BOQ</button>}
    </span>
  )
  return (
    <div ref={box} className="relative w-full max-w-md">
      <Input autoFocus aria-label={`Work item for ${lineLabel(line)}`} leading={<Search />} value={text} onChange={(e) => setText(e.target.value)}
        placeholder="Search work item code or name" trailing={<button type="button" aria-label="Close" onClick={() => setOpen(false)}><X className="size-4" /></button>} />
      <ul role="listbox" className="absolute top-full z-30 mt-1 max-h-64 w-full overflow-auto rounded-md border border-input bg-popover py-1 text-sm shadow-md">
        {(found.data?.items ?? []).map((w) => (
          <li key={w.id} role="option" aria-selected={false}>
            <button type="button" className="flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left hover:bg-accent" onClick={() => set.mutate(w.id)}>
              <span className="min-w-0 truncate"><span className="font-mono text-xs text-muted-foreground">{w.code}</span> {w.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{w.unit}{w.norms ? ` · ${w.norms} norms` : ''}</span>
            </button>
          </li>
        ))}
        {!found.isFetching && !(found.data?.items ?? []).length && <li className="px-3 py-2 text-muted-foreground">No work item found. Work items are added in the Item Master.</li>}
      </ul>
    </div>
  )
}

/** BOQ lines with no work item, each with the one its description clearly reads like: tick the right ones and use them. */
export function MatchWorksModal({ job, onClose }: { job: number; onClose: () => void }) {
  const list = useQuery({ queryKey: ['item-sheet-work-suggestions', job], queryFn: () => workSuggestions(job) })
  const [off, setOff] = useState<Set<string>>(new Set())
  const items = useMemo(() => list.data?.items ?? [], [list.data])
  const chosen = items.filter((s) => !off.has(s.key))
  const use = useAction(() => setLineWorks(job, chosen.map((s) => ({ boq_key: s.key, work_item_id: s.work.id }))), {
    invalidate: [itemSheetKeys.one(job)], success: () => `Work items set for ${plural(chosen.length, 'BOQ line')}.`, onSuccess: onClose,
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title="Match BOQ lines to work items"
      description="For lines whose BOQ names no work item: the work item of the Item Master whose name reads like the line, in the same unit. Untick any that are wrong."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={() => use.mutate()} loading={use.isPending} disabled={!chosen.length}>Use {plural(chosen.length, 'match', 'matches')}</Button></>}>
      {list.isPending && <p className="text-sm text-muted-foreground">Looking for matches...</p>}
      {list.data && !items.length && <p className="text-sm text-muted-foreground">No clear match found. Choose the work item on each line with "Which work item is this?", or add work items to the Item Master.</p>}
      {items.length > 0 && (
        <ul className="max-h-[60vh] space-y-2 overflow-auto" aria-label="Suggested work items">
          {items.map((s) => (
            <li key={s.key}>
              <label className="flex items-start gap-3 rounded-lg border border-border p-3 text-sm">
                <input type="checkbox" className="mt-1" checked={!off.has(s.key)} aria-label={`Use ${s.work.name} for ${lineLabel(s)}`}
                  onChange={() => setOff((o) => { const n = new Set(o); if (n.has(s.key)) n.delete(s.key); else n.add(s.key); return n })} />
                <span className="min-w-0">
                  <span className="block font-medium">{lineLabel(s)}</span>
                  <span className="block text-muted-foreground">→ <span className="font-mono text-xs">{s.work.code}</span> {s.work.name} ({s.work.unit}){s.work.norms ? ` · ${plural(s.work.norms, 'material')} in its norms` : ''}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}

/** What the work done so far should have used, by the sheet, against what the store issued for it: line by line. */
export function ConsumptionTab({ s }: { s: ItemSheet }) {
  const rows = s.groups.flatMap((g) => g.lines).filter((l) => l.done_qty !== null && l.materials.length > 0)
  if (!rows.length) return (
    <Card className="p-6 text-sm text-muted-foreground">
      Nothing to check yet. Once work is measured on a contractor's work order (or the programme shows progress on a BOQ line), each of its
      materials is shown here: what that much work should have used by this sheet, against what was issued for the line.
    </Card>
  )
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Should have used = the sheet's quantity for the line x the share of the line done. Over by more than 5% is marked.</p>
      {rows.map((l) => {
        const share = l.qty > 0 && l.done_qty !== null ? (l.done_qty / l.qty) * 100 : 0
        return (
          <Card key={l.key} className="overflow-hidden">
            <div className="border-b border-border bg-muted/40 px-4 py-2.5 text-sm">
              <p className="font-medium">{lineLabel(l)}</p>
              <p className="text-xs text-muted-foreground">
                Done {formatQty(l.done_qty ?? 0)} of {formatQty(l.qty)} {l.unit} ({formatQty(Math.round(share * 10) / 10)}%) · {l.done_from === 'measured' ? 'measured on work orders' : 'by the programme'}
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label={`Consumption for ${lineLabel(l)}`}>
                <thead className="text-xs uppercase tracking-wide text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="px-4 py-2 text-left font-medium">Material</th>
                    <th className="px-3 py-2 text-right font-medium">Should have used</th>
                    <th className="px-3 py-2 text-right font-medium">Issued</th>
                    <th className="px-3 py-2 text-right font-medium">Difference</th>
                  </tr>
                </thead>
                <tbody>
                  {l.materials.map((m) => {
                    const should = m.should_use ?? 0
                    const diff = m.issued - should
                    const pct = should > 0 ? (diff / should) * 100 : null
                    const over = pct !== null ? pct > 5 : m.issued > 0
                    return (
                      <tr key={m.id} className="border-b border-border last:border-0">
                        <td className="px-4 py-2"><p>{m.item_name}</p><p className="font-mono text-xs text-muted-foreground">{m.item_code}</p></td>
                        <td className="px-3 py-2 text-right tabular">{formatQty(should)} {m.unit}</td>
                        <td className="px-3 py-2 text-right tabular">{formatQty(m.issued)} {m.unit}</td>
                        <td className={`px-3 py-2 text-right tabular ${over ? 'font-semibold text-danger' : 'text-muted-foreground'}`}>
                          {diff > 0 ? '+' : ''}{formatQty(Math.round(diff * 1000) / 1000)} {m.unit}{pct !== null && ` (${diff > 0 ? '+' : ''}${Math.round(pct)}%)`}
                          {over && <span className="sr-only"> over</span>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        )
      })}
    </div>
  )
}
