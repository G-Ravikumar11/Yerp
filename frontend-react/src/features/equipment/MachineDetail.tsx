import { Button, Skeleton, Stat, StatGrid } from '@/components/ui'
import { useMachine } from '@/api/equipment'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const th = 'px-3 py-2 text-left text-xs font-medium text-muted-foreground'

/** One machine's history: its days, its services, where it has been. */
export function MachineDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useMachine(id)
  const d = q.data
  if (q.isPending || !d) return <Skeleton className="mt-6 h-40 w-full" />
  return (
    <section aria-label={`${d.code} history`} className="mt-6 rounded-xl border border-border bg-card p-5 shadow-card">
      <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">{d.code} {d.name}</h2><Button size="sm" variant="outline" onClick={onClose}>Close</Button></div>
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Where" value={d.current_job || 'Yard'} />
        <Stat label="Utilisation" value={`${d.utilisation_percent}%`} />
        <Stat label="Diesel" value={`${d.litres_per_hour} L/h`} />
        <Stat label="Cost to date" value={formatINR(d.cost_to_date)} />
      </StatGrid>
      {d.service.reasons.length > 0 && <p className={`mb-4 rounded-lg border p-2.5 text-[13px] ${d.service.due ? 'border-danger/40 text-danger' : 'border-warning/40 text-warning'}`}>{d.service.reasons.join('; ')}</p>}
      <h3 className="mb-2 text-sm font-semibold">Daily log</h3>
      <div className="mb-5 overflow-x-auto rounded-lg border border-border"><table aria-label="Daily log" className="w-full text-[13px]"><thead className="bg-surface"><tr><th className={th}>Date</th><th className={th}>Site</th><th className={`${th} text-right`}>Worked h</th><th className={`${th} text-right`}>Idle h</th><th className={`${th} text-right`}>Diesel L</th><th className={`${th} text-right`}>Cost</th><th className={th}>Operator</th><th className={th}>Work</th></tr></thead>
        <tbody>{d.logs.length ? d.logs.map((l, i) => <tr key={i} className="border-t border-border"><td className="px-3 py-2">{formatDate(l.log_date)}</td><td className="px-3 py-2">{l.job}</td><td className="px-3 py-2 text-right tabular">{l.hours_worked}</td><td className="px-3 py-2 text-right tabular">{l.idle_hours}</td><td className="px-3 py-2 text-right tabular">{l.fuel_litres}</td><td className="px-3 py-2 text-right tabular">{formatINR(l.fuel_cost + l.hire_cost)}</td><td className="px-3 py-2">{l.operator}</td><td className="px-3 py-2">{l.work_done}</td></tr>) : <tr><td colSpan={8} className="px-3 py-4 text-center text-muted-foreground">No days logged.</td></tr>}</tbody></table></div>
      <h3 className="mb-2 text-sm font-semibold">Services and repairs</h3>
      <div className="mb-5 overflow-x-auto rounded-lg border border-border"><table aria-label="Services" className="w-full text-[13px]"><thead className="bg-surface"><tr><th className={th}>Date</th><th className={th}>Kind</th><th className={th}>What</th><th className={th}>By</th><th className={`${th} text-right`}>Meter</th><th className={`${th} text-right`}>Down h</th><th className={`${th} text-right`}>Cost</th></tr></thead>
        <tbody>{d.services.length ? d.services.map((s, i) => <tr key={i} className="border-t border-border"><td className="px-3 py-2">{formatDate(s.service_on)}</td><td className="px-3 py-2">{s.kind}</td><td className="px-3 py-2">{s.description}</td><td className="px-3 py-2">{s.vendor}</td><td className="px-3 py-2 text-right tabular">{s.meter_at_service ?? ''}</td><td className="px-3 py-2 text-right tabular">{s.downtime_hours || ''}</td><td className="px-3 py-2 text-right tabular">{formatINR(s.total_cost)}</td></tr>) : <tr><td colSpan={7} className="px-3 py-4 text-center text-muted-foreground">No services recorded.</td></tr>}</tbody></table></div>
      <h3 className="mb-2 text-sm font-semibold">Movements</h3>
      {d.moves.length ? <ul className="grid gap-1 text-[13px]">{d.moves.map((m, i) => <li key={i}>{formatDate(m.moved_on)} &nbsp; {m.from} to <strong>{m.to}</strong>{m.note && <span className="text-muted-foreground"> {m.note}</span>}</li>)}</ul> : <p className="text-[13px] text-muted-foreground">Never moved.</p>}
    </section>
  )
}
