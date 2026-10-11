import { useState } from 'react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Field, Select, Stat, StatGrid } from '@/components/ui'
import { useTdsRegister, type Deducted, type Suffered } from '@/api/registers'
import { formatDate } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

const QUARTERS = [['Q1', 'Q1 - Apr to Jun'], ['Q2', 'Q2 - Jul to Sep'], ['Q3', 'Q3 - Oct to Dec'], ['Q4', 'Q4 - Jan to Mar']]

/** TDS under section 194C, both ways: what we withhold and deposit, and what was withheld from us to claim. */
export function TdsTab() {
  const [year, setYear] = useState('')
  const [quarter, setQuarter] = useState('')
  const q = useTdsRegister(year, quarter)
  const d = q.data
  const s = d?.summary

  const dedCols: TableColumn<Deducted>[] = [
    { id: 'date', header: 'Date', cell: (r) => formatDate(r.date) },
    { id: 'q', header: 'Quarter', hideBelow: 'md', cell: (r) => `${r.year} ${r.quarter}` },
    { id: 'bill', header: 'Bill', cell: (r) => <span className="font-mono text-[13px]">{r.bill}</span> },
    { id: 'who', header: 'Deductee', cell: (r) => <div>{r.deductee}{r.missing_pan ? <div className="text-[11px] text-danger">no PAN - 20% applies</div> : <div className="font-mono text-[11px] text-muted-foreground">{r.pan}</div>}</div> },
    { id: 'sec', header: 'Section', hideBelow: 'lg', cell: (r) => `${r.section} @ ${r.rate}%` },
    { id: 'amt', header: 'Amount credited', hideBelow: 'md', align: 'right', cell: (r) => formatINR(r.amount_credited) },
    { id: 'tds', header: 'TDS', align: 'right', cell: (r) => <span className="font-semibold">{formatINR(r.tds)}</span> },
    { id: 'paid', header: 'Deposited', hideBelow: 'lg', cell: (r) => formatDate(r.paid_on) || '-' },
  ]

  const sufCols: TableColumn<Suffered>[] = [
    { id: 'date', header: 'Date', cell: (r) => formatDate(r.date) },
    { id: 'q', header: 'Quarter', hideBelow: 'md', cell: (r) => `${r.year} ${r.quarter}` },
    { id: 'bill', header: 'Bill', cell: (r) => <span className="font-mono text-[13px]">{r.bill}</span> },
    { id: 'who', header: 'Deducted by', cell: (r) => <div>{r.deductor}<div className="text-[11px] text-muted-foreground">{r.project}</div></div> },
    { id: 'sec', header: 'Section', hideBelow: 'lg', cell: (r) => `${r.section} @ ${r.rate}%` },
    { id: 'amt', header: 'Amount credited', hideBelow: 'md', align: 'right', cell: (r) => formatINR(r.amount_credited) },
    { id: 'tds', header: 'TDS', align: 'right', cell: (r) => <span className="font-semibold">{formatINR(r.tds)}</span> },
  ]

  const quarterCols: TableColumn<NonNullable<typeof d>['deducted_by_quarter'][number]>[] = [
    { id: 'p', header: 'Quarter', cell: (r) => <span className="font-semibold">{r.period}</span> },
    { id: 'b', header: 'Bills', align: 'right', cell: (r) => r.bills },
    { id: 'a', header: 'Amount credited', align: 'right', cell: (r) => formatINR(r.amount_credited) },
    { id: 't', header: 'TDS to deposit', align: 'right', cell: (r) => <span className="font-semibold">{formatINR(r.tds)}</span> },
  ]

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end gap-4 rounded-xl border border-border bg-card p-4">
        <div className="w-44"><Field label="Financial year" htmlFor="tds-year"><Select id="tds-year" value={year} onChange={(e) => setYear(e.target.value)} placeholder="Every year" options={(d?.years ?? []).map((y) => ({ value: y, label: y }))} /></Field></div>
        <div className="w-52"><Field label="Quarter" htmlFor="tds-q"><Select id="tds-q" value={quarter} onChange={(e) => setQuarter(e.target.value)} placeholder="Every quarter" options={QUARTERS.map(([v, l]) => ({ value: v, label: l }))} /></Field></div>
        <p className="min-w-60 flex-1 text-[13px] text-muted-foreground">What we withheld is deposited by the 7th of the next month and filed in the 26Q each quarter. What was withheld from us is matched to the 26AS before it is claimed.</p>
      </div>
      <StatGrid className="xl:grid-cols-3">
        <Stat label="Deducted by us (to deposit)" value={compactINR(s?.deducted)} loading={q.isPending} />
        <Stat label="Deducted from us (to claim)" value={compactINR(s?.suffered)} loading={q.isPending} />
        <Stat label="Deductees without a PAN" value={s?.deductees_without_pan ?? 0} tone={s?.deductees_without_pan ? 'danger' : undefined} loading={q.isPending} />
      </StatGrid>
      <h2 className="mb-3 text-lg font-semibold">By quarter</h2>
      <DataTable label="TDS by quarter" rows={d?.deducted_by_quarter ?? []} columns={quarterCols} rowKey={(r) => r.period} loading={q.isPending} empty="Nothing deducted in this period." className="mb-8" />
      <h2 className="mb-3 text-lg font-semibold">Deducted by us</h2>
      <DataTable label="TDS deducted by us" rows={d?.deducted ?? []} columns={dedCols} rowKey={(r) => `${r.bill}-${r.date}`} loading={q.isPending} empty="Nothing deducted in this period." className="mb-8" />
      <h2 className="mb-3 text-lg font-semibold">Deducted from us</h2>
      <DataTable label="TDS deducted from us" rows={d?.suffered ?? []} columns={sufCols} rowKey={(r) => `${r.bill}-${r.date}`} loading={q.isPending} empty="Nothing deducted from us in this period." />
    </>
  )
}
