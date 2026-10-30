import { useEffect, useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { Badge, Button, Input, Modal, Select, Skeleton, Tabs } from '@/components/ui'
import { pullBoqLines, useAvailable, useBoqs, type AvailableLine, type ScheduleRow } from '@/api/boq'
import { useAction } from '@/lib/mutate'
import { formatQty } from '@/lib/format'
import { formatINR, cn } from '@/lib/utils'
import { toast } from '@/stores/toast'

interface Pick {
  quantity: string
  rate: string
}

type Left = 'all' | 'open' | 'none' | 'part' | 'full'

const LEFT_FILTERS: { value: Left; label: string }[] = [
  { value: 'all', label: 'All lines' },
  { value: 'open', label: 'Still to give' },
  { value: 'none', label: 'Not given yet' },
  { value: 'part', label: 'Partly given' },
  { value: 'full', label: 'Fully given' },
]

const LEVELS = ['Main headings', 'Sub-headings', 'Sub-sub-headings', 'Fourth-level headings']
const NO_HEADING = 'Items not under a heading'
const SOURCE: Record<string, string> = { budget: 'from the budget', 'last given': 'last rate given', mixed: 'budget / last given' }

/** Where a line stands: nothing given to a contractor, some of it, or all of it (or more). */
const standing = (l: AvailableLine): 'none' | 'part' | 'full' => {
  const given = l.given ?? 0
  if (given <= 0) return 'none'
  return (l.left ?? 0) > 0 ? 'part' : 'full'
}

/** A heading taken as one line: what is still to give under it, in one unit (and one grade, unless grades are put together). */
interface Group {
  id: string
  headingKey: string
  title: string
  trail: string
  code: string
  uom: string
  material: string
  lines: AvailableLine[]
  left: number
  rate: number
  rateFrom: string
}

/** Lines added up as one: their suggested rates weighted by quantity, as the server would. */
function blend(lines: AvailableLine[]) {
  const priced = lines.filter((l) => (l.suggested_rate ?? 0) > 0 && (l.left ?? 0) > 0)
  const qty = priced.reduce((n, l) => n + (l.left ?? 0), 0)
  if (!qty) return { rate: 0, from: '' }
  const from = new Set(priced.map((l) => l.rate_from ?? ''))
  return { rate: Math.round((priced.reduce((n, l) => n + (l.left ?? 0) * (l.suggested_rate ?? 0), 0) / qty) * 100) / 100, from: from.size === 1 ? [...from][0] : 'mixed' }
}

/**
 * Lines of the project BOQ, taken into this order's schedule as the sheet has them: each under its main heading and
 * sub-heading, with the text written under the heading, its grade, and a contractor rate filled in from the budget (or the
 * rate it was last given at), which can be changed. A heading can be taken as one line, its quantities added up. What is
 * added comes back as the whole schedule, laid out like the sheet and numbered.
 */
export function BoqPicker({
  orderId,
  jobId,
  open,
  onOpenChange,
  onAdd,
  current,
  startMode = 'lines',
}: {
  orderId: number
  jobId: number
  open: boolean
  onOpenChange: (o: boolean) => void
  onAdd: (rows: ScheduleRow[]) => void
  /** The schedule on screen, so what is added lands in it in the BOQ's order. */
  current: Partial<ScheduleRow>[]
  startMode?: 'lines' | 'headings'
}) {
  const boqs = useBoqs()
  const boq = (boqs.data?.boqs ?? []).find((b) => b.job_id === jobId)
  const avail = useAvailable(open && boq ? boq.id : 0)
  const [picks, setPicks] = useState<Record<string, Pick>>({})
  const [search, setSearch] = useState('')
  const [section, setSection] = useState('')
  const [left, setLeft] = useState<Left>('open')
  const [onlyTicked, setOnlyTicked] = useState(false)
  const [mode, setMode] = useState<'lines' | 'headings'>(startMode)
  const [level, setLevel] = useState(0)
  const [keepGrades, setKeepGrades] = useState(true)
  const [gpicks, setGpicks] = useState<Record<string, string>>({})
  // Opened from "Add BOQ headings" it starts on the headings; from "Add from the project BOQ", line by line.
  useEffect(() => {
    if (open) setMode(startMode)
  }, [open, startMode])

  const lines = useMemo(() => avail.data?.lines ?? [], [avail.data])
  const heads = useMemo(() => new Map(lines.filter((l) => l.kind === 'section').map((l) => [l.key!, l])), [lines])
  const items = useMemo(() => lines.filter((l) => l.kind !== 'section' && l.kind !== 'note'), [lines])
  const deepest = useMemo(() => Math.max(0, ...[...heads.values()].map((h) => h.level ?? 0)), [heads])
  const sections = useMemo(
    () => [...heads.values()].map((h) => ({ value: h.key!, label: `${'— '.repeat(h.level ?? 0)}${`${h.item_no || ''} ${h.description}`.trim()}` })),
    [heads],
  )
  const under = (l: AvailableLine) => !section || (l.path ?? []).includes(section)
  const matches = (l: AvailableLine, q: string) =>
    !q || `${l.item_no ?? ''} ${l.group_code} ${l.item_code ?? ''} ${l.description} ${l.material ?? ''} ${(l.path ?? []).map((k) => heads.get(k)?.description ?? '').join(' ')}`.toLowerCase().includes(q)

  // Line by line: the lines that pass the filters, with every heading above them, in the sheet's order.
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase()
    const keep = new Set(
      items
        .filter((l) => {
          if (!under(l)) return false
          if (left === 'open' && (l.left ?? 0) <= 0) return false
          if ((left === 'none' || left === 'part' || left === 'full') && standing(l) !== left) return false
          if (onlyTicked && !picks[l.key!]) return false
          return matches(l, q)
        })
        .map((l) => l.key!),
    )
    const needed = new Set(items.filter((l) => keep.has(l.key!)).flatMap((l) => l.path ?? []))
    return lines.filter((l) => (l.kind === 'section' ? needed.has(l.key!) : keep.has(l.key ?? '')))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lines, items, search, section, left, onlyTicked, picks])

  // By heading: one line per heading at the level chosen, per unit, and per grade unless grades are put together.
  const groups = useMemo(() => {
    const q = search.trim().toLowerCase()
    const out = new Map<string, Group>()
    for (const l of items) {
      if ((l.left ?? 0) <= 0 || !under(l) || !matches(l, q)) continue
      const path = l.path ?? []
      const headingKey = path.length ? path[Math.min(level, path.length - 1)] : ''
      const h = heads.get(headingKey)
      const grade = (l.material ?? '').trim()
      const id = `${headingKey}|${(l.uom ?? '').trim().toLowerCase()}|${keepGrades ? grade.toLowerCase() : ''}`
      const g =
        out.get(id) ??
        ({
          id,
          headingKey,
          title: h?.description ?? NO_HEADING,
          trail: (h?.path ?? []).map((k) => heads.get(k)?.description ?? '').join(' › '),
          code: h?.group_code ?? '',
          uom: l.uom ?? '',
          material: grade,
          lines: [],
          left: 0,
          rate: 0,
          rateFrom: '',
        } as Group)
      if (g.material !== grade) g.material = keepGrades ? grade : 'Mixed'
      g.lines.push(l)
      g.left += l.left ?? 0
      out.set(id, g)
    }
    const list = [...out.values()]
    for (const g of list) Object.assign(g, (({ rate, from }) => ({ rate, rateFrom: from }))(blend(g.lines)))
    return list
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, heads, search, section, level, keepGrades])
  // The words on a heading's line: its name, its grade, and its unit when the same heading has the same grade in two units.
  const describe = (g: Group) => {
    const grade = keepGrades && g.material ? ` - ${g.material}` : ''
    const twin = groups.some((o) => o !== g && o.headingKey === g.headingKey && (keepGrades ? o.material === g.material : true))
    return `${g.title}${grade}${twin && g.uom ? ` (${g.uom})` : ''}`
  }

  const pricedCount = items.length
  const ticked = Object.entries(picks)
  const incomplete = ticked.some(([, p]) => !(Number(p.quantity) > 0) || !(Number(p.rate) > 0))
  const value = ticked.reduce((n, [, p]) => n + (Number(p.quantity) || 0) * (Number(p.rate) || 0), 0)
  const takeable = shown.filter((l) => l.kind !== 'section' && (l.left ?? 0) > 0)
  const allTaken = takeable.length > 0 && takeable.every((l) => picks[l.key!])
  const filtered = !!search || !!section || left !== 'open' || onlyTicked

  const gticked = groups.filter((g) => g.id in gpicks)
  const gincomplete = gticked.some((g) => !(Number(gpicks[g.id]) > 0))
  const gvalue = gticked.reduce((n, g) => n + g.left * (Number(gpicks[g.id]) || 0), 0)
  const headings = mode === 'headings'
  const count = ticked.length + gticked.length
  const total = value + gvalue
  const add = useAction(
    () =>
      pullBoqLines(
        orderId,
        ticked.map(([key, p]) => ({ key, quantity: Number(p.quantity), rate: Number(p.rate) })),
        gticked.map((g) => ({
          heading_key: g.headingKey,
          description: describe(g),
          group_code: '',
          rate: Number(gpicks[g.id]),
          parts: g.lines.map((l) => ({ key: l.key!, quantity: l.left ?? 0 })),
        })),
        current,
      ),
    {
      onSuccess: (r) => {
        onAdd(r.rows ?? [...r.headings, ...r.lines])
        r.warnings.forEach((w) => toast.info(w))
        setPicks({})
        setGpicks({})
        onOpenChange(false)
      },
    },
  )
  const ticks = [ticked.length && `${ticked.length} ${ticked.length === 1 ? 'line' : 'lines'}`, gticked.length && `${gticked.length} ${gticked.length === 1 ? 'heading' : 'headings'}`]
    .filter(Boolean)
    .join(' and ')

  const start = (l: AvailableLine): Pick => ({ quantity: String(l.left || ''), rate: (l.suggested_rate ?? 0) > 0 ? String(l.suggested_rate) : '' })
  const toggle = (l: AvailableLine, on: boolean) =>
    setPicks((s) => {
      const next = { ...s }
      if (on) next[l.key!] = start(l)
      else delete next[l.key!]
      return next
    })
  // Every line still to give under a heading, at once - or none of them.
  const toggleMany = (list: AvailableLine[], on: boolean) =>
    setPicks((s) => {
      const next = { ...s }
      for (const l of list) {
        if (on) next[l.key!] = next[l.key!] ?? start(l)
        else delete next[l.key!]
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
  const regroup = (fn: () => void) => {
    fn()
    setGpicks({})
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title="Build the work order from the project BOQ"
      description={
        boq
          ? `${boq.number} ${boq.revision}. The quantity offered is what is still to be given to a contractor. The contractor rate is filled in from the budget (or the rate last given) and can be changed.`
          : undefined
      }
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <div className="text-[13px] text-muted-foreground">
            {count ? (
              <>
                <span className="font-medium text-foreground">{ticks}</span> ticked
                {total > 0 && <> · <span className="tabular font-medium text-foreground">{formatINR(total)}</span> at contractor rates</>}
                {(incomplete || gincomplete) && <span className="text-warning"> · give every ticked line a rate</span>}
              </>
            ) : headings ? (
              'Tick the headings this contractor is to do. Each becomes one line, under its main heading.'
            ) : (
              'Tick the BOQ lines this contractor is to do. Their headings come with them.'
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button loading={add.isPending} disabled={!count || incomplete || gincomplete} onClick={() => add.mutate()}>
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
              { value: 'headings', label: 'By heading (cumulative)' },
            ]}
          />
          <div className={cn('grid gap-2', headings ? 'sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,0.8fr)]' : 'sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)]')}>
            <Input aria-label="Search the BOQ" leading={<Search />} placeholder="Search description, heading, grade, code..." value={search} onChange={(e) => setSearch(e.target.value)} />
            <Select aria-label="Heading of the BOQ" value={section} onChange={(e) => regroup(() => setSection(e.target.value))} placeholder="All headings" options={sections} />
            {headings ? (
              <Select
                aria-label="Add up under"
                value={String(level)}
                onChange={(e) => regroup(() => setLevel(Number(e.target.value)))}
                options={LEVELS.slice(0, deepest + 1).map((label, i) => ({ value: String(i), label: `Add up under ${label.toLowerCase()}` }))}
              />
            ) : (
              <Select aria-label="How much is given" value={left} onChange={(e) => setLeft(e.target.value as Left)} options={LEFT_FILTERS} />
            )}
          </div>

          {headings ? (
            <>
              <div className="flex flex-wrap items-center gap-3 text-[13px]">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={groups.length > 0 && groups.every((g) => g.id in gpicks)}
                    disabled={!groups.length}
                    onChange={(e) => setGpicks(e.target.checked ? Object.fromEntries(groups.map((g) => [g.id, gpicks[g.id] ?? (g.rate > 0 ? String(g.rate) : '')])) : {})}
                  />
                  Tick all {groups.length}
                </label>
                <label className="flex items-center gap-2" title="Grades often have different rates, so each grade is its own line unless they are put together">
                  <input type="checkbox" checked={keepGrades} onChange={(e) => regroup(() => setKeepGrades(e.target.checked))} />
                  Keep each grade separate
                </label>
                <span className="text-muted-foreground">What is still to give under each heading, added up. Different units are never added together.</span>
              </div>
              <div className="max-h-[26rem] overflow-y-auto rounded-lg border border-border">
                <table aria-label="Headings of the project BOQ" className="w-full text-[13px]">
                  <thead className="sticky top-0 z-10 bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="w-10 px-3 py-2" />
                      <th className="px-2 py-2">Heading</th>
                      <th className="px-2 py-2">Material</th>
                      <th className="px-2 py-2 text-right">BOQ lines</th>
                      <th className="px-2 py-2 text-right">Total quantity</th>
                      <th className="w-32 px-2 py-2 text-right">Contractor rate</th>
                      <th className="px-2 py-2 text-right">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.length === 0 && (
                      <tr>
                        <td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">
                          Nothing is left to give under these headings.
                        </td>
                      </tr>
                    )}
                    {groups.map((g) => (
                      <tr key={g.id} className={cn('border-t border-border', g.id in gpicks && 'bg-primary/5')}>
                        <td className="px-3 py-1.5">
                          <input
                            type="checkbox"
                            aria-label={`Take ${describe(g)}`}
                            checked={g.id in gpicks}
                            onChange={(e) =>
                              setGpicks((s) => {
                                const n = { ...s }
                                if (e.target.checked) n[g.id] = g.rate > 0 ? String(g.rate) : ''
                                else delete n[g.id]
                                return n
                              })
                            }
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          {g.trail && <span className="block text-[11px] text-muted-foreground">{g.trail} ›</span>}
                          <span className="font-medium">{describe(g)}</span>
                        </td>
                        <td className="px-2 py-1.5">{g.material ? <Badge tone={g.material === 'Mixed' ? 'warning' : 'neutral'}>{g.material}</Badge> : <span className="text-muted-foreground">-</span>}</td>
                        <td className="tabular px-2 py-1.5 text-right text-muted-foreground" title={g.lines.map((l) => l.description).join('\n')}>
                          {g.lines.length}
                        </td>
                        <td className="tabular px-2 py-1.5 text-right">
                          {formatQty(g.left)} {g.uom}
                        </td>
                        <td className="px-2 py-1">
                          {g.id in gpicks && (
                            <>
                              <input
                                aria-label={`Contractor rate of ${describe(g)}`}
                                inputMode="decimal"
                                placeholder="Rs / unit"
                                className="h-8 w-full rounded-md border border-input bg-background px-2 text-right"
                                value={gpicks[g.id]}
                                onChange={(e) => setGpicks((s) => ({ ...s, [g.id]: e.target.value }))}
                              />
                              {g.rate > 0 && Number(gpicks[g.id]) === g.rate && <span className="block text-right text-[10px] text-muted-foreground">{SOURCE[g.rateFrom] ?? ''}</span>}
                            </>
                          )}
                        </td>
                        <td className="tabular px-2 py-1.5 text-right">{g.id in gpicks && Number(gpicks[g.id]) > 0 ? formatINR(g.left * Number(gpicks[g.id])) : '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3 text-[13px]">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={allTaken} disabled={!takeable.length} onChange={(e) => toggleMany(takeable, e.target.checked)} />
                  Tick all {takeable.length} shown
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={onlyTicked} onChange={(e) => setOnlyTicked(e.target.checked)} />
                  Only ticked
                </label>
                <span className="text-muted-foreground">
                  Showing {shown.filter((l) => l.kind !== 'section').length} of {pricedCount} lines
                </span>
                {filtered && (
                  <button type="button" className="text-primary underline-offset-2 hover:underline" onClick={reset}>
                    Clear filters
                  </button>
                )}
              </div>

              <div className="max-h-[26rem] overflow-y-auto rounded-lg border border-border">
                <table aria-label="Lines of the project BOQ" className="w-full text-[13px]">
                  <thead className="sticky top-0 z-10 bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="w-10 px-3 py-2" />
                      <th className="px-2 py-2">Description</th>
                      <th className="px-2 py-2">Material</th>
                      <th className="px-2 py-2 text-right">BOQ qty</th>
                      <th className="px-2 py-2 text-right">BOQ rate</th>
                      <th className="px-2 py-2 text-right">Given</th>
                      <th className="px-2 py-2 text-right">Left</th>
                      <th className="w-28 px-2 py-2 text-right">Quantity</th>
                      <th className="w-32 px-2 py-2 text-right">Contractor rate</th>
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
                    {shown.map((l) => {
                      if (l.kind === 'section') {
                        const mine = takeable.filter((x) => (x.path ?? []).includes(l.key!))
                        const all = mine.length > 0 && mine.every((x) => picks[x.key!])
                        return (
                          <tr key={l.key} className="border-t border-border bg-surface/60">
                            <td className="px-3 py-1.5 align-top">
                              <input type="checkbox" aria-label={`Take everything under ${l.description}`} checked={all} disabled={!mine.length} onChange={(e) => toggleMany(mine, e.target.checked)} />
                            </td>
                            <td colSpan={8} className="px-2 py-1.5" style={{ paddingLeft: `${0.5 + (l.level ?? 0) * 1.25}rem` }}>
                              <span className={cn('font-semibold', (l.level ?? 0) > 0 && 'text-[12.5px]')}>{`${l.item_no || ''} ${l.description}`.trim()}</span>
                              {l.notes && (
                                <span className="mt-0.5 line-clamp-2 block text-xs italic text-muted-foreground" title={l.notes}>
                                  {l.notes}
                                </span>
                              )}
                            </td>
                          </tr>
                        )
                      }
                      const k = l.key!
                      const room = l.left ?? 0
                      const st = standing(l)
                      const p = picks[k]
                      return (
                        <tr key={k} className={cn('border-t border-border', p && 'bg-primary/5')}>
                          <td className="px-3 py-1.5">
                            <input type="checkbox" aria-label={`Take ${l.description}`} checked={!!p} onChange={(e) => toggle(l, e.target.checked)} />
                          </td>
                          <td className="max-w-xs px-2 py-1.5" style={{ paddingLeft: `${0.5 + (l.path?.length ?? 0) * 1.25}rem` }} title={[l.description, l.remarks].filter(Boolean).join('\n')}>
                            <span className="block truncate">{l.description}</span>
                            {(l.item_no || l.item_code) && <span className="font-mono text-[11px] text-muted-foreground">{[l.item_no, l.item_code].filter(Boolean).join(' · ')}</span>}
                          </td>
                          <td className="px-2 py-1.5">{l.material ? <Badge tone="neutral">{l.material}</Badge> : <span className="text-muted-foreground">-</span>}</td>
                          <td className="tabular px-2 py-1.5 text-right">
                            {formatQty(l.quantity ?? 0)} {l.uom}
                          </td>
                          <td className="tabular px-2 py-1.5 text-right text-muted-foreground">{l.rate ? formatINR(l.rate) : '-'}</td>
                          <td className="px-2 py-1.5 text-right">
                            {st === 'none' ? <span className="text-muted-foreground">-</span> : <Badge tone={st === 'full' ? 'success' : 'warning'}>{formatQty(l.given ?? 0)}</Badge>}
                          </td>
                          <td className={cn('tabular px-2 py-1.5 text-right', !room && 'text-muted-foreground')}>{formatQty(room)}</td>
                          <td className="px-2 py-1">
                            {p && <input aria-label={`Quantity of ${l.description}`} inputMode="decimal" className="h-8 w-full rounded-md border border-input bg-background px-2 text-right" value={p.quantity} onChange={(e) => set(k, 'quantity', e.target.value)} />}
                          </td>
                          <td className="px-2 py-1">
                            {p && (
                              <>
                                <input aria-label={`Contractor rate of ${l.description}`} inputMode="decimal" placeholder="Rs / unit" className="h-8 w-full rounded-md border border-input bg-background px-2 text-right" value={p.rate} onChange={(e) => set(k, 'rate', e.target.value)} />
                                {(l.suggested_rate ?? 0) > 0 && Number(p.rate) === l.suggested_rate && <span className="block text-right text-[10px] text-muted-foreground">{SOURCE[l.rate_from ?? ''] ?? ''}</span>}
                              </>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}
