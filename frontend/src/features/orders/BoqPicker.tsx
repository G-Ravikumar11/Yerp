import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { Badge, Button, Input, Modal, Select, Skeleton, Tabs } from '@/components/ui'
import { pullBoqLines, useAvailable, useBoqs, type AvailableLine } from '@/api/boq'
import { useAction } from '@/lib/mutate'
import { formatQty } from '@/lib/format'
import { formatINR, cn } from '@/lib/utils'
import { toast } from '@/stores/toast'

interface Pick {
  quantity: string
  rate: string
}

/** A heading of the BOQ taken as one line: what is left under it in one unit, added up. */
interface Group {
  id: string
  code: string
  title: string
  uom: string
  lines: AvailableLine[]
  left: number
}

type Left = 'all' | 'open' | 'none' | 'part' | 'full'

const LEFT_FILTERS: { value: Left; label: string }[] = [
  { value: 'all', label: 'All lines' },
  { value: 'open', label: 'Still to give' },
  { value: 'none', label: 'Not given yet' },
  { value: 'part', label: 'Partly given' },
  { value: 'full', label: 'Fully given' },
]

/** Where a line stands: nothing given to a contractor, some of it, or all of it (or more). */
const standing = (l: AvailableLine): 'none' | 'part' | 'full' => {
  const given = l.given ?? 0
  if (given <= 0) return 'none'
  return (l.left ?? 0) > 0 ? 'part' : 'full'
}

/**
 * Lines of the project's BOQ, taken into this order's schedule: filter to the part of the BOQ this contractor is
 * doing, tick the lines, say how much of each and at what contractor rate. Each keeps its link to the BOQ line, so
 * what is given out is added up against what the client's BOQ allows.
 */
export function BoqPicker({ orderId, jobId, open, onOpenChange, onAdd }: { orderId: number; jobId: number; open: boolean; onOpenChange: (o: boolean) => void; onAdd: (lines: Record<string, unknown>[]) => void }) {
  const boqs = useBoqs()
  const boq = (boqs.data?.boqs ?? []).find((b) => b.job_id === jobId)
  const avail = useAvailable(open && boq ? boq.id : 0)
  const [picks, setPicks] = useState<Record<string, Pick>>({})
  const [search, setSearch] = useState('')
  const [section, setSection] = useState('')
  const [left, setLeft] = useState<Left>('open')
  const [onlyTicked, setOnlyTicked] = useState(false)
  const [mode, setMode] = useState<'lines' | 'headings'>('lines')
  const [gpicks, setGpicks] = useState<Record<string, string>>({})

  // Each priced line with the heading it sits under, so the BOQ can be cut down by section.
  const all = useMemo(() => {
    let head = ''
    let code = ''
    let title = ''
    return (avail.data?.lines ?? []).map((l) => {
      if (l.kind === 'section') {
        head = `${l.group_code} ${l.description}`.trim()
        code = l.group_code
        title = l.description
      }
      return { line: l, head, code, title }
    })
  }, [avail.data])

  // One row per heading and unit, like the totals in an Excel schedule: only what is still to give, and never across units.
  const groups = useMemo(() => {
    const q = search.trim().toLowerCase()
    const out = new Map<string, Group>()
    for (const { line: l, head, code, title } of all) {
      if (l.kind === 'section' || (l.left ?? 0) <= 0 || !head) continue
      if (section && head !== section) continue
      if (q && !`${head} ${l.description}`.toLowerCase().includes(q)) continue
      const id = `${head}||${(l.uom ?? '').trim().toLowerCase()}`
      const g = out.get(id) ?? { id, code, title, uom: l.uom ?? '', lines: [], left: 0 }
      g.lines.push(l)
      g.left += l.left ?? 0
      out.set(id, g)
    }
    return [...out.values()]
  }, [all, search, section])
  const sections = useMemo(() => [...new Set(all.filter((r) => r.line.kind === 'section').map((r) => r.head))], [all])

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase()
    const keep = all.filter(({ line: l, head }) => {
      if (l.kind === 'section') return false
      if (section && head !== section) return false
      if (left === 'open' && (l.left ?? 0) <= 0) return false
      if ((left === 'none' || left === 'part' || left === 'full') && standing(l) !== left) return false
      if (onlyTicked && !picks[l.key!]) return false
      if (q && !`${l.group_code} ${l.item_code ?? ''} ${l.description}`.toLowerCase().includes(q)) return false
      return true
    })
    // Headings come back only above lines that survived, so the list still reads as the BOQ.
    const out: { line: AvailableLine; head: string; first: boolean }[] = []
    let last = ''
    for (const r of keep) {
      out.push({ ...r, first: r.head !== last })
      last = r.head
    }
    return out
  }, [all, search, section, left, onlyTicked, picks])

  const pricedCount = all.filter((r) => r.line.kind !== 'section').length
  const ticked = Object.entries(picks)
  const incomplete = ticked.some(([, p]) => !(Number(p.quantity) > 0) || !(Number(p.rate) > 0))
  const value = ticked.reduce((n, [, p]) => n + (Number(p.quantity) || 0) * (Number(p.rate) || 0), 0)
  const takeable = shown.filter((r) => (r.line.left ?? 0) > 0)
  const allTaken = takeable.length > 0 && takeable.every((r) => picks[r.line.key!])
  const filtered = !!search || !!section || left !== 'open' || onlyTicked

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

  const gticked = groups.filter((g) => g.id in gpicks)
  const gincomplete = gticked.some((g) => !(Number(gpicks[g.id]) > 0))
  const gvalue = gticked.reduce((n, g) => n + g.left * (Number(gpicks[g.id]) || 0), 0)
  const addGroups = useAction(
    () =>
      pullBoqLines(
        orderId,
        [],
        gticked.map((g) => ({ description: g.title, group_code: g.code, rate: Number(gpicks[g.id]), parts: g.lines.map((l) => ({ key: l.key!, quantity: l.left ?? 0 })) })),
      ),
    {
      onSuccess: (r) => {
        onAdd(r.lines)
        r.warnings.forEach((w) => toast.info(w))
        setGpicks({})
        onOpenChange(false)
      },
    },
  )
  const headings = mode === 'headings'
  const count = headings ? gticked.length : ticked.length

  const toggle = (key: string, room: number, on: boolean) =>
    setPicks((s) => {
      const next = { ...s }
      if (on) next[key] = { quantity: String(room || ''), rate: '' }
      else delete next[key]
      return next
    })
  const toggleShown = (on: boolean) =>
    setPicks((s) => {
      const next = { ...s }
      for (const r of takeable) {
        const k = r.line.key!
        if (on) next[k] = next[k] ?? { quantity: String(r.line.left ?? ''), rate: '' }
        else delete next[k]
      }
      return next
    })
  const set = (key: string, field: keyof Pick, value: string) => setPicks((s) => ({ ...s, [key]: { ...s[key], [field]: value } }))
  const reset = () => {
    setSearch('')
    setSection('')
    setLeft('open')
    setOnlyTicked(false)
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title="Build the work order from the project BOQ"
      description={boq ? `${boq.number} ${boq.revision}. The quantity offered is what is still to be given to a contractor; the contractor rate is yours to type.` : undefined}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <div className="text-[13px] text-muted-foreground">
            {count ? (
              <>
                <span className="font-medium text-foreground">{count}</span> {headings ? (count === 1 ? 'heading' : 'headings') : count === 1 ? 'line' : 'lines'} ticked
                {(headings ? gvalue : value) > 0 && <> · <span className="tabular font-medium text-foreground">{formatINR(headings ? gvalue : value)}</span> at contractor rates</>}
              </>
            ) : headings ? (
              'Tick the headings this contractor is to do. Each becomes one line.'
            ) : (
              'Tick the BOQ lines this contractor is to do.'
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button loading={add.isPending || addGroups.isPending} disabled={!count || (headings ? gincomplete : incomplete)} onClick={() => (headings ? addGroups.mutate() : add.mutate())}>
              Add {count || ''} {count === 1 ? 'line' : 'lines'} to the work order
            </Button>
          </div>
        </div>
      }
    >
      {boqs.isPending || (boq && avail.isPending) ? (
        <Skeleton className="h-48 w-full" />
      ) : !boq ? (
        <p className="py-8 text-center text-sm text-muted-foreground">This project has no BOQ yet. Start one under Projects, BOQ, then come back to build the work order from it.</p>
      ) : (
        <div className="space-y-3">
          <Tabs
            label="How to take the BOQ"
            value={mode}
            onChange={setMode}
            items={[
              { value: 'lines', label: 'Line by line' },
              { value: 'headings', label: 'By heading (one line each)' },
            ]}
          />
          <div className={cn('grid gap-2', headings ? 'sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]' : 'sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)]')}>
            <Input aria-label="Search the BOQ" leading={<Search />} placeholder="Search description, item code, group..." value={search} onChange={(e) => setSearch(e.target.value)} />
            <Select aria-label="Section of the BOQ" value={section} onChange={(e) => setSection(e.target.value)} placeholder="All sections" options={sections.map((s) => ({ value: s, label: s }))} />
            {!headings && <Select aria-label="How much is given" value={left} onChange={(e) => setLeft(e.target.value as Left)} options={LEFT_FILTERS} />}
          </div>
          {headings && (
            <>
              <div className="flex flex-wrap items-center gap-3 text-[13px]">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={groups.length > 0 && groups.every((g) => g.id in gpicks)}
                    disabled={!groups.length}
                    onChange={(e) => setGpicks(e.target.checked ? Object.fromEntries(groups.map((g) => [g.id, gpicks[g.id] ?? ''])) : {})}
                  />
                  Tick all {groups.length} headings
                </label>
                <span className="text-muted-foreground">Each heading becomes one line: what is still to give under it, added up. Lines in different units stay apart.</span>
              </div>
              <div className="max-h-[24rem] overflow-y-auto rounded-lg border border-border">
                <table aria-label="Headings of the project BOQ" className="w-full text-[13px]">
                  <thead className="sticky top-0 z-10 bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="w-10 px-3 py-2" />
                      <th className="px-2 py-2">Heading</th>
                      <th className="px-2 py-2 text-right">BOQ lines</th>
                      <th className="px-2 py-2 text-right">Total quantity</th>
                      <th className="w-32 px-2 py-2 text-right">Contractor rate</th>
                      <th className="px-2 py-2 text-right">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                          Nothing is left to give under any heading.
                        </td>
                      </tr>
                    )}
                    {groups.map((g) => (
                      <tr key={g.id} className={cn('border-t border-border', g.id in gpicks && 'bg-primary/5')}>
                        <td className="px-3 py-1.5">
                          <input
                            type="checkbox"
                            aria-label={`Take ${g.title}`}
                            checked={g.id in gpicks}
                            onChange={(e) => setGpicks((s) => { const n = { ...s }; if (e.target.checked) n[g.id] = ''; else delete n[g.id]; return n })}
                          />
                        </td>
                        <td className="px-2 py-1.5 font-medium">
                          {`${g.code} ${g.title}`.trim()}
                          {groups.filter((o) => o.title === g.title && o.code === g.code).length > 1 && <span className="ml-1.5 font-normal text-muted-foreground">in {g.uom}</span>}
                        </td>
                        <td className="tabular px-2 py-1.5 text-right text-muted-foreground">{g.lines.length}</td>
                        <td className="tabular px-2 py-1.5 text-right">
                          {formatQty(g.left)} {g.uom}
                        </td>
                        <td className="px-2 py-1">
                          {g.id in gpicks && (
                            <input aria-label={`Contractor rate of ${g.title}`} inputMode="decimal" placeholder="Rs / unit" className="h-8 w-full rounded-md border border-input bg-background px-2 text-right" value={gpicks[g.id]} onChange={(e) => setGpicks((s) => ({ ...s, [g.id]: e.target.value }))} />
                          )}
                        </td>
                        <td className="tabular px-2 py-1.5 text-right">{g.id in gpicks && Number(gpicks[g.id]) > 0 ? formatINR(g.left * Number(gpicks[g.id])) : '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {!headings && (<>
          <div className="flex flex-wrap items-center gap-3 text-[13px]">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={allTaken} disabled={!takeable.length} onChange={(e) => toggleShown(e.target.checked)} />
              Tick all {takeable.length} shown
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={onlyTicked} onChange={(e) => setOnlyTicked(e.target.checked)} />
              Only ticked
            </label>
            <span className="text-muted-foreground">
              Showing {shown.length} of {pricedCount} lines
            </span>
            {filtered && (
              <button type="button" className="text-primary underline-offset-2 hover:underline" onClick={reset}>
                Clear filters
              </button>
            )}
          </div>

          <div className="max-h-[24rem] overflow-y-auto rounded-lg border border-border">
            <table aria-label="Lines of the project BOQ" className="w-full text-[13px]">
              <thead className="sticky top-0 z-10 bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="w-10 px-3 py-2" />
                  <th className="px-2 py-2">Group</th>
                  <th className="px-2 py-2">Description</th>
                  <th className="px-2 py-2 text-right">BOQ qty</th>
                  <th className="px-2 py-2 text-right">BOQ rate</th>
                  <th className="px-2 py-2 text-right">Given</th>
                  <th className="px-2 py-2 text-right">Left</th>
                  <th className="w-28 px-2 py-2 text-right">Quantity</th>
                  <th className="w-28 px-2 py-2 text-right">Contractor rate</th>
                </tr>
              </thead>
              <tbody>
                {shown.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">
                      No BOQ line matches those filters.
                    </td>
                  </tr>
                )}
                {shown.map(({ line: l, head, first }) => {
                  const k = l.key!
                  const room = l.left ?? 0
                  const st = standing(l)
                  return [
                    first && head ? (
                      <tr key={`h-${k}`} className="border-t border-border bg-surface/60">
                        <td colSpan={9} className="px-3 py-1.5 font-semibold">
                          {head}
                        </td>
                      </tr>
                    ) : null,
                    <tr key={k} className={cn('border-t border-border', picks[k] && 'bg-primary/5')}>
                      <td className="px-3 py-1.5">
                        <input type="checkbox" aria-label={`Take ${l.description}`} checked={!!picks[k]} onChange={(e) => toggle(k, room, e.target.checked)} />
                      </td>
                      <td className="px-2 py-1.5 font-mono text-xs">{l.group_code}</td>
                      <td className="max-w-xs truncate px-2 py-1.5" title={l.description}>
                        {l.description}
                      </td>
                      <td className="tabular px-2 py-1.5 text-right">
                        {formatQty(l.quantity ?? 0)} {l.uom}
                      </td>
                      <td className="tabular px-2 py-1.5 text-right text-muted-foreground">{l.rate ? formatINR(l.rate) : '-'}</td>
                      <td className="px-2 py-1.5 text-right">
                        {st === 'none' ? <span className="text-muted-foreground">-</span> : <Badge tone={st === 'full' ? 'success' : 'warning'}>{formatQty(l.given ?? 0)}</Badge>}
                      </td>
                      <td className={cn('tabular px-2 py-1.5 text-right', !room && 'text-muted-foreground')}>{formatQty(room)}</td>
                      <td className="px-2 py-1">
                        {picks[k] && <input aria-label={`Quantity of ${l.description}`} inputMode="decimal" className="h-8 w-full rounded-md border border-input bg-background px-2 text-right" value={picks[k].quantity} onChange={(e) => set(k, 'quantity', e.target.value)} />}
                      </td>
                      <td className="px-2 py-1">
                        {picks[k] && <input aria-label={`Contractor rate of ${l.description}`} inputMode="decimal" placeholder="Rs / unit" className="h-8 w-full rounded-md border border-input bg-background px-2 text-right" value={picks[k].rate} onChange={(e) => set(k, 'rate', e.target.value)} />}
                      </td>
                    </tr>,
                  ]
                })}
              </tbody>
            </table>
          </div>
          </>)}
        </div>
      )}
    </Modal>
  )
}
