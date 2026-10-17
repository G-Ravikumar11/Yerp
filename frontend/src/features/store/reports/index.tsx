
import { useQuery } from '@tanstack/react-query'
import { Link, Route, Routes } from 'react-router-dom'
import { Card, Stat } from '@/components/ui'
import { storeGet } from '@/api/store'
import { StoreShell } from '../StoreShell'
import { Norms } from './Norms'
import { ReportView } from './ReportView'

/** Store > Reports: stock, movement, consumption against BOQ norms, and the other slices' registers - on screen, as Excel and as PDF. */
export default function ReportsIndex() {
  return (
    <StoreShell slice="reports">
      <Routes>
        <Route index element={<Home />} />
        <Route path="run/:code" element={<ReportView />} />
        <Route path="norms" element={<Norms />} />
      </Routes>
    </StoreShell>
  )
}

interface Summary { stock_value: string; stock_lines: number; below_reorder: number; in_transit: number; returnables_late: number; open_writeoffs: number }
const GROUPS: { title: string; codes: string[] }[] = [
  { title: 'Stock', codes: ['stock-valuation', 'stock-movement', 'reorder', 'slow-moving'] },
  { title: 'Cost and consumption', codes: ['consumption', 'subcon-material'] },
  { title: 'Registers', codes: ['po-pending', 'returnables', 'in-transit', 'count-variances', 'scrap'] },
]
const BLURB: Record<string, string> = {
  'stock-valuation': 'What each store holds and what it is worth, today or on a past date.',
  'stock-movement': 'Opening, received, issued and closing for a period.',
  reorder: 'Items at or below their reorder level, with how much to order.',
  'slow-moving': 'Stock that has not been issued for a long time.',
  consumption: 'Material charged to a project, net of returns, against BOQ norms.',
  'subcon-material': 'Material given to a subcontractor and what is recoverable from their bills.',
  'po-pending': 'Purchase order lines still to be received.',
  returnables: 'Returnable items still out, who holds them, how late.',
  'in-transit': 'Stock sent between stores and not yet received.',
  'count-variances': 'What stock counts found against the books.',
  scrap: 'Scrap taken out, book value against what it fetched.',
}

function Home() {
  const summary = useQuery({ queryKey: ['store', 'reports', 'summary'], queryFn: () => storeGet<Summary>('reports', '/summary') })
  const cat = useQuery({ queryKey: ['store', 'reports', 'catalog'], queryFn: () => storeGet<{ reports: { code: string; title: string }[] }>('reports', '/catalog') })
  const s = summary.data
  const titles = Object.fromEntries((cat.data?.reports ?? []).map((r) => [r.code, r.title]))
  return (
    <div className="space-y-8">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Stock value" value={s ? `₹${Number(s.stock_value).toLocaleString('en-IN')}` : '—'} sub={s ? `${s.stock_lines} lines` : undefined} loading={summary.isLoading} to="run/stock-valuation" />
        <Stat label="To reorder" value={s?.below_reorder ?? '—'} tone={s?.below_reorder ? 'warning' : undefined} loading={summary.isLoading} to="run/reorder" />
        <Stat label="In transit" value={s?.in_transit ?? '—'} loading={summary.isLoading} to="run/in-transit" />
        <Stat label="Returnables late" value={s?.returnables_late ?? '—'} tone={s?.returnables_late ? 'danger' : undefined} loading={summary.isLoading} to="run/returnables" />
        <Stat label="Open write-offs" value={s?.open_writeoffs ?? '—'} loading={summary.isLoading} />
      </div>
      {GROUPS.map((g) => (
        <section key={g.title}>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">{g.title}</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {g.codes.map((c) => (
              <Link key={c} to={`run/${c}`}>
                <Card className="h-full p-4 transition-colors hover:bg-accent/40"><div className="font-medium">{titles[c] ?? c}</div><p className="mt-1 text-sm text-muted-foreground">{BLURB[c]}</p></Card>
              </Link>
            ))}
          </div>
        </section>
      ))}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Set-up</h2>
        <Link to="norms"><Card className="p-4 transition-colors hover:bg-accent/40"><div className="font-medium">Consumption norms</div><p className="mt-1 text-sm text-muted-foreground">How much of an item each BOQ item should take; the consumption report compares issues against it.</p></Card></Link>
      </section>
    </div>
  )
}
