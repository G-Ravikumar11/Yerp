import { useState } from 'react'
import { Button, Skeleton, Stat, StatGrid } from '@/components/ui'
import { useMachine } from '@/api/equipment'
import { formatDate } from '@/lib/format'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'
import { ServiceBadge } from './plantParts'
import { ServiceDoneModal } from './ServiceDoneModal'

const th = 'px-3 py-2 text-left text-xs font-medium text-muted-foreground'
const TYPE_LABEL = { Both: 'Meter reading + calendar days', Meter: 'Meter reading only', Days: 'Calendar days only', None: 'No service schedule' }
const ACTION_LABEL: Record<string, string> = { 'plant.schedule.set': 'Schedule set', 'plant.schedule.changed': 'Schedule changed', 'plant.service.completed': 'Service completed' }

/** One machine's history: its schedule, its days, its services, where it has been. */
export function MachineDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useMachine(id)
  const { can } = useSession()
  const [doing, setDoing] = useState(false)
  const d = q.data
  if (q.isPending || !d) return <Skeleton className="mt-6 h-40 w-full" />
  const s = d.service.schedule
  const live = !d.is_archived && !['Disposed', 'Returned'].includes(d.status)
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

      <div aria-label="Service schedule" className="mb-5 rounded-lg border border-border p-3.5">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold">Service schedule</h3><ServiceBadge status={s.status} />
          {s.type !== 'None' && live && can('site.record') && <Button size="sm" className="ml-auto" variant={d.service.due ? 'primary' : 'outline'} onClick={() => setDoing(true)}>Service done</Button>}
        </div>
        <dl className="grid gap-x-6 gap-y-1.5 text-[13px] sm:grid-cols-2 lg:grid-cols-3">
          <div><dt className="text-xs text-muted-foreground">Interval</dt><dd>{TYPE_LABEL[s.type]}{s.type !== 'None' && `: ${[s.every_meter ? `every ${s.every_meter.toLocaleString('en-IN')} ${s.unit}` : '', s.every_days ? `every ${s.every_days} days` : ''].filter(Boolean).join(' or ')}`}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Last service</dt><dd>{[s.last_service_on ? formatDate(s.last_service_on) : '', s.last_service_meter !== null && s.type !== 'Days' ? `${s.last_service_meter.toLocaleString('en-IN')} ${s.unit}` : ''].filter(Boolean).join(' at ') || 'Not recorded'}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Next due</dt><dd className="font-medium">{[s.next_meter !== null ? `${s.next_meter.toLocaleString('en-IN')} ${s.unit}` : '', s.next_on ? formatDate(s.next_on) : ''].filter(Boolean).join(' or ') || '-'}</dd></div>
          {s.type !== 'None' && <div><dt className="text-xs text-muted-foreground">To go</dt><dd>{[s.meter_left !== null ? (s.meter_left >= 0 ? `${s.meter_left} ${s.unit}` : `${-s.meter_left} ${s.unit} past`) : '', s.days_left !== null ? (s.days_left >= 0 ? `${s.days_left} days` : `${-s.days_left} days past`) : ''].filter(Boolean).join(', ') || '-'}</dd></div>}
          {s.type !== 'None' && <div><dt className="text-xs text-muted-foreground">Early reminder</dt><dd>{[s.type !== 'Days' ? `${s.reminder_meter} ${s.unit}` : '', s.type !== 'Meter' ? `${s.reminder_days} days` : ''].filter(Boolean).join(' or ')} before{!s.reminder_meter_set && !s.reminder_days_set && ' (a tenth of the interval)'}</dd></div>}
          {s.missing.length > 0 && <div className="sm:col-span-2 lg:col-span-3 text-warning">Not recorded: {s.missing.join(', ')}.</div>}
        </dl>
      </div>

      <h3 className="mb-2 text-sm font-semibold">Service history</h3>
      <div className="mb-5 overflow-x-auto rounded-lg border border-border"><table aria-label="Services" className="w-full min-w-[52rem] text-[13px]"><thead className="bg-surface"><tr><th className={th}>Date</th><th className={th}>Kind</th><th className={`${th} text-right`}>Meter</th><th className={th}>Work performed</th><th className={th}>Parts used</th><th className={th}>By</th><th className={`${th} text-right`}>Cost</th><th className={th}>Next due</th></tr></thead>
        <tbody>{d.services.length ? d.services.map((v) => (
          <tr key={v.id} className="border-t border-border align-top">
            <td className="px-3 py-2 whitespace-nowrap">{formatDate(v.service_on)}{v.number && <div className="font-mono text-[11px] text-muted-foreground">{v.number}</div>}</td>
            <td className="px-3 py-2">{v.kind}</td>
            <td className="px-3 py-2 text-right tabular">{v.meter_at_service ?? '-'}</td>
            <td className="px-3 py-2">{v.work_performed || v.description}</td>
            <td className="px-3 py-2">{v.parts_used || '-'}</td>
            <td className="px-3 py-2">{v.vendor}</td>
            <td className="px-3 py-2 text-right tabular">{formatINR(v.total_cost)}</td>
            <td className="px-3 py-2">{[v.next_service_meter !== null ? `${v.next_service_meter.toLocaleString('en-IN')} ${s.unit}` : '', v.next_service_on ? formatDate(v.next_service_on) : ''].filter(Boolean).join(' or ') || '-'}</td>
          </tr>
        )) : <tr><td colSpan={8} className="px-3 py-4 text-center text-muted-foreground">No services recorded.</td></tr>}</tbody></table></div>

      {d.schedule_history.length > 0 && (
        <>
          <h3 className="mb-2 text-sm font-semibold">Schedule changes</h3>
          <ul aria-label="Schedule changes" className="mb-5 grid gap-1 text-[13px]">{d.schedule_history.map((h, i) => <li key={i}><span className="text-muted-foreground">{h.at}</span> <strong>{ACTION_LABEL[h.action] ?? h.action}</strong> {h.details}{h.by && <span className="text-muted-foreground"> - {h.by}</span>}</li>)}</ul>
        </>
      )}

      <h3 className="mb-2 text-sm font-semibold">Daily log</h3>
      <div className="mb-5 overflow-x-auto rounded-lg border border-border"><table aria-label="Daily log" className="w-full text-[13px]"><thead className="bg-surface"><tr><th className={th}>Date</th><th className={th}>Site</th><th className={`${th} text-right`}>Worked h</th><th className={`${th} text-right`}>Idle h</th><th className={`${th} text-right`}>Diesel L</th><th className={`${th} text-right`}>Cost</th><th className={th}>Operator</th><th className={th}>Work</th></tr></thead>
        <tbody>{d.logs.length ? d.logs.map((l, i) => <tr key={i} className="border-t border-border"><td className="px-3 py-2">{formatDate(l.log_date)}</td><td className="px-3 py-2">{l.job}</td><td className="px-3 py-2 text-right tabular">{l.hours_worked}</td><td className="px-3 py-2 text-right tabular">{l.idle_hours}</td><td className="px-3 py-2 text-right tabular">{l.fuel_litres}</td><td className="px-3 py-2 text-right tabular">{formatINR(l.fuel_cost + l.hire_cost)}</td><td className="px-3 py-2">{l.operator}</td><td className="px-3 py-2">{l.work_done}</td></tr>) : <tr><td colSpan={8} className="px-3 py-4 text-center text-muted-foreground">No days logged.</td></tr>}</tbody></table></div>
      <h3 className="mb-2 text-sm font-semibold">Movements</h3>
      {d.moves.length ? <ul className="grid gap-1 text-[13px]">{d.moves.map((m, i) => <li key={i}>{formatDate(m.moved_on)} &nbsp; {m.from} to <strong>{m.to}</strong>{m.note && <span className="text-muted-foreground"> {m.note}</span>}</li>)}</ul> : <p className="text-[13px] text-muted-foreground">Never moved.</p>}
      <ServiceDoneModal machine={doing ? d : null} onClose={() => setDoing(false)} />
    </section>
  )
}
