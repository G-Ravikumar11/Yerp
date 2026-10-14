import { useState } from 'react'
import { FileSpreadsheet, FileText } from 'lucide-react'
import { Button, Card, Select, Skeleton } from '@/components/ui'
import { reportUrl, useCosts, useProviders, type Range } from '@/api/plant'
import { formatINR } from '@/lib/utils'
import { LoadError, MachineSelect, PersonSelect, RangeBar } from './plantParts'

const REPORTS: [string, string, string][] = [
  ['register', 'Equipment register', 'Every machine: ID, ownership, status, condition, where it is, its meter and service'],
  ['allocations', 'Equipment allocation history', 'Who worked which machine, in which shift, from when to when'],
  ['employee-hours', 'Employee working hours', 'Hours on duty, regular and overtime, by employee and month'],
  ['machine-hours', 'Machine operating hours', 'Running, idle and breakdown hours by machine'],
  ['fuel', 'Fuel consumption and expenditure', 'Every fill: litres, rate, amount, supplier and voucher'],
  ['maintenance', 'Maintenance and breakdown history', 'Requests, work done, costs and downtime'],
  ['rentals', 'Rental agreements and returns', 'Agreements, dates, rates, hours used against billed, status'],
  ['rental-invoices', 'Rental invoices and outstanding', 'Each invoice, what is paid and what is still owed'],
  ['expenses', 'Equipment expenses', 'Every machine cost, from every register, once'],
  ['overtime', 'Employee overtime', 'Days on which overtime was worked, by employee'],
]

/** What each machine cost for the period, and every report to take away - in Excel or PDF, filtered the same way. */
export function PlantReports() {
  const [r, setR] = useState({ from: '', to: '', asset: 0, emp: 0, ownership: '', status: '', provider: 0 })
  const providers = useProviders()
  const range: Range & { ownership?: string } = { date_from: r.from, date_to: r.to, asset_id: r.asset, employee_id: r.emp, status: r.status, provider_id: r.provider }
  const q = useCosts({ date_from: r.from, date_to: r.to, asset_id: r.asset })
  const url = (kind: string, pdf = false) => reportUrl(kind, range, pdf) + (r.ownership ? `${reportUrl(kind, range, pdf).includes('?') ? '&' : '?'}ownership=${encodeURIComponent(r.ownership)}` : '')
  return (
    <div>
      <RangeBar from={r.from} to={r.to} onChange={(from, to) => setR((x) => ({ ...x, from, to }))}>
        <div className="w-48"><MachineSelect id="rp-m" value={r.asset} onChange={(asset) => setR((x) => ({ ...x, asset }))} placeholder="Every machine" /></div>
        <div className="w-48"><PersonSelect id="rp-e" value={r.emp} onChange={(emp) => setR((x) => ({ ...x, emp }))} placeholder="Every employee" /></div>
        <div className="w-36"><Select aria-label="Ownership" value={r.ownership} placeholder="Any ownership" onChange={(e) => setR((x) => ({ ...x, ownership: e.target.value }))} options={['Owned', 'Rented', 'Leased'].map((x) => ({ value: x, label: x }))} /></div>
        <div className="w-40"><Select aria-label="Machine status" value={r.status} placeholder="Any status" onChange={(e) => setR((x) => ({ ...x, status: e.target.value }))} options={[['Deployed', 'Working'], ['Available', 'Available'], ['Under repair', 'Maintenance'], ['Breakdown', 'Breakdown'], ['Returned', 'Returned']].map(([v, l]) => ({ value: v, label: l }))} /></div>
        <div className="w-44"><Select aria-label="Rental provider" value={r.provider || ''} placeholder="Any provider" onChange={(e) => setR((x) => ({ ...x, provider: Number(e.target.value) || 0 }))} options={(providers.data?.providers ?? []).map((p) => ({ value: p.id, label: p.name }))} /></div>
      </RangeBar>

      <Card className="mb-5 overflow-hidden">
        <div className="border-b border-border px-4 py-2.5"><h2 className="text-sm font-semibold">Cost by machine</h2></div>
        {q.isError ? <div className="p-4"><LoadError message={q.error.message} retry={() => q.refetch()} /></div> : q.isPending ? <Skeleton className="m-4 h-32" /> : (
          <div className="overflow-x-auto">
            <table aria-label="Cost by machine" className="w-full min-w-[56rem] text-[13px]">
              <thead className="bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground"><tr><th className="px-3 py-2">Machine</th><th className="px-3 text-right">Running h</th><th className="px-3 text-right">Fuel</th><th className="px-3 text-right">Fuel / h</th><th className="px-3 text-right">Maintenance</th><th className="px-3 text-right">Rental</th><th className="px-3 text-right">Rental owed</th><th className="px-3 text-right">Other</th><th className="px-3 text-right">Labour h</th><th className="px-3 text-right">Labour (est.)</th><th className="px-3 text-right">Total</th></tr></thead>
              <tbody>
                {q.data!.machines.filter((m) => m.total || m.operating_hours || m.labour_hours).map((m) => (
                  <tr key={m.asset_id} className="border-t border-border"><td className="px-3 py-2"><span className="font-mono">{m.code}</span> {m.name}</td><td className="px-3 text-right tabular">{m.operating_hours}</td><td className="px-3 text-right tabular">{formatINR(m.fuel)}</td><td className="px-3 text-right tabular">{m.fuel_per_hour ? formatINR(m.fuel_per_hour) : '-'}</td><td className="px-3 text-right tabular">{formatINR(m.maintenance)}</td><td className="px-3 text-right tabular">{formatINR(m.rental)}</td><td className="px-3 text-right tabular">{formatINR(m.rental_outstanding)}</td><td className="px-3 text-right tabular">{formatINR(m.other_expenses)}</td><td className="px-3 text-right tabular">{m.labour_hours}</td><td className="px-3 text-right tabular text-muted-foreground">{formatINR(m.labour_cost)}</td><td className="px-3 text-right tabular font-semibold">{formatINR(m.total)}</td></tr>
                ))}
                {q.data!.machines.every((m) => !(m.total || m.operating_hours || m.labour_hours)) && <tr><td colSpan={11} className="p-6 text-center text-muted-foreground">No cost or hours recorded for this period.</td></tr>}
              </tbody>
              <tfoot className="border-t-2 border-border font-semibold"><tr><td className="px-3 py-2">Total</td><td className="px-3 text-right tabular">{q.data!.totals.operating_hours}</td><td className="px-3 text-right tabular">{formatINR(q.data!.totals.fuel)}</td><td /><td className="px-3 text-right tabular">{formatINR(q.data!.totals.maintenance)}</td><td className="px-3 text-right tabular">{formatINR(q.data!.totals.rental)}</td><td className="px-3 text-right tabular">{formatINR(q.data!.totals.rental_outstanding)}</td><td className="px-3 text-right tabular">{formatINR(q.data!.totals.other_expenses)}</td><td className="px-3 text-right tabular">{q.data!.totals.labour_hours}</td><td className="px-3 text-right tabular text-muted-foreground">{formatINR(q.data!.totals.labour_cost)}</td><td className="px-3 text-right tabular">{formatINR(q.data!.totals.total)}</td></tr></tfoot>
            </table>
            <p className="px-4 py-2 text-[11px] text-muted-foreground">Labour is worked out from logged hours and each person's pay, for reference; wages enter the total only as expenses entered, so nothing is counted twice.</p>
          </div>
        )}
      </Card>

      <div className="grid gap-2 sm:grid-cols-2">
        {REPORTS.map(([kind, title, what]) => (
          <Card key={kind} className="flex flex-wrap items-center gap-3 p-3.5">
            <div className="min-w-0 flex-1"><p className="text-sm font-semibold">{title}</p><p className="text-xs text-muted-foreground">{what}</p></div>
            <Button size="sm" variant="outline" asChild><a href={url(kind)}><FileSpreadsheet /> Excel</a></Button>
            <Button size="sm" variant="outline" asChild><a href={url(kind, true)} target="_blank" rel="noopener"><FileText /> PDF</a></Button>
          </Card>
        ))}
      </div>
    </div>
  )
}
