import { useState } from 'react'
import { ChevronDown, ChevronRight, Download } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, Stat, StatGrid } from '@/components/ui'
import { earnedValueFileUrl, useEarnedValue, type EvHeading, type EvLine } from '@/api/earnedValue'
import { cn, compactINR, formatINR } from '@/lib/utils'

type Row = (EvHeading & { heading: true }) | (EvLine & { heading?: false; level?: number })
const ratio = (v: number | null) => (v === null ? '-' : v.toFixed(2))
const tone = (v: number | null) => (v === null ? undefined : v < 0.95 ? 'danger' : v < 1 ? 'warning' : 'success') as 'danger' | 'warning' | 'success' | undefined

/** Budget against actual by BOQ heading and line: planned value, earned value, actual cost, CPI and SPI. */
export function EarnedValueView({ job }: { job: number }) {
  const q = useEarnedValue(job)
  const v = q.data
  const t = v?.total
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const heads = v?.headings ?? []
  // Headings in BOQ order, each opening onto its sub-headings and lines; only a heading whose headings above are open shows.
  const shown = (path: string[]) => path.every((k) => open[k])
  const rows: Row[] = []
  for (const h of heads) {
    if (!shown(h.path)) continue
    rows.push({ ...h, heading: true })
    if (open[h.key]) {
      for (const l of v?.lines ?? []) if (l.path[l.path.length - 1] === h.key) rows.push({ ...l, heading: false, level: h.level + 1 })
    }
  }
  if (!heads.length) rows.push(...(v?.lines ?? []).map((l) => ({ ...l, heading: false as const })))
  const cols: TableColumn<Row>[] = [
    { id: 'what', header: 'Heading / line', cell: (r) => (r.heading
      ? <button type="button" onClick={() => setOpen((o) => ({ ...o, [r.key]: !o[r.key] }))} aria-expanded={!!open[r.key]} style={{ paddingLeft: `${r.level * 1.25}rem` }} className={cn('flex max-w-[24rem] items-center gap-2 text-left font-bold', r.level === 0 && 'uppercase')}>
          {open[r.key] ? <ChevronDown className="size-4 shrink-0" /> : <ChevronRight className="size-4 shrink-0" />}<span>{r.item_no} {r.description}</span>
        </button>
      : <div className="max-w-[24rem]" style={{ paddingLeft: `${(r.level ?? 0) * 1.25}rem` }}><p className="line-clamp-2">{r.item_no} {r.description}</p>
          <p className="text-xs text-muted-foreground">{!r.budgeted ? 'not budgeted' : r.progress_from === '' ? 'no activity on the programme' : r.progress_from === 'heading' ? 'progress from its heading' : ''}{r.ac > 0 ? `${r.budgeted ? '' : ' · '}material ${compactINR(r.material)} · subcontract ${compactINR(r.subcontract)}` : ''}</p></div>) },
    { id: 'bud', header: 'Budget', align: 'right', cell: (r) => formatINR(r.budget) },
    { id: 'pct', header: 'Planned / done', align: 'right', hideBelow: 'md', cell: (r) => <span className="tabular">{r.planned_percent}% / {r.done_percent}%</span> },
    { id: 'pv', header: 'Planned value', align: 'right', hideBelow: 'lg', cell: (r) => formatINR(r.pv) },
    { id: 'ev', header: 'Earned value', align: 'right', cell: (r) => formatINR(r.ev) },
    { id: 'ac', header: 'Actual cost', align: 'right', cell: (r) => <span className={r.overrun ? 'font-semibold text-danger' : ''}>{formatINR(r.ac)}</span> },
    { id: 'cpi', header: 'CPI', align: 'right', hideBelow: 'sm', cell: (r) => ratio(r.cpi) },
    { id: 'spi', header: 'SPI', align: 'right', hideBelow: 'sm', cell: (r) => ratio(r.spi) },
    { id: 'flag', header: '', cell: (r) => (r.overrun ? <Badge tone="danger">Over</Badge> : null) },
  ]
  const loose = (v?.not_against_a_line.material ?? 0) + (v?.not_against_a_line.subcontract ?? 0)
  return (
    <section aria-label="Budget against actual">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] text-muted-foreground">As of {v?.as_of ?? '-'}. Earned value is the budget times how far the work is on the programme; actual cost is material issued from the stores and subcontract work measured, against each BOQ line.</p>
        <Button variant="outline" size="sm" disabled={!v} onClick={() => window.open(earnedValueFileUrl(job), '_blank')}><Download /> Excel</Button>
      </div>
      <StatGrid>
        <Stat label="Budget" value={compactINR(t?.budget)} loading={q.isPending} />
        <Stat label="Planned value" value={compactINR(t?.pv)} sub={t ? `${t.planned_percent}% by today` : undefined} loading={q.isPending} />
        <Stat label="Earned value" value={compactINR(t?.ev)} sub={t ? `${t.done_percent}% done` : undefined} loading={q.isPending} />
        <Stat label="Actual cost" value={compactINR(t?.ac)} sub={loose ? `${compactINR(loose)} not against a BOQ line` : undefined} loading={q.isPending} />
        <Stat label="CPI" value={ratio(t?.cpi ?? null)} tone={tone(t?.cpi ?? null)} sub="earned / actual" loading={q.isPending} />
        <Stat label="SPI" value={ratio(t?.spi ?? null)} tone={tone(t?.spi ?? null)} sub="earned / planned" loading={q.isPending} />
        <Stat label="Cost at completion" value={t?.eac != null ? compactINR(t.eac) : '-'} sub={t?.vac != null ? `${t.vac < 0 ? 'over' : 'under'} budget by ${compactINR(Math.abs(t.vac))}` : undefined} tone={t?.vac != null && t.vac < 0 ? 'danger' : undefined} loading={q.isPending} />
        <Stat label="Headings over budget" value={t?.overruns ?? 0} tone={(t?.overruns ?? 0) > 0 ? 'danger' : undefined} sub="cost past budget x % done" loading={q.isPending} />
      </StatGrid>
      {t && t.lines_with_progress === 0 && t.budget > 0 && <Card className="my-3 p-3 text-[13px]">No activity on the programme is drawn on this BOQ, so nothing counts as done yet. Draw the programme from the BOQ in Planning &amp; Progress and earned value follows the work.</Card>}
      <div className="mt-4">
        <DataTable label="Budget against actual by BOQ heading" rows={rows} columns={cols} rowKey={(r) => (r.heading ? 'h:' : 'l:') + r.key} loading={q.isPending}
          rowClassName={(r) => (r.heading ? 'font-semibold bg-surface/60' : undefined)} empty="The BOQ has no priced lines." />
      </div>
    </section>
  )
}
