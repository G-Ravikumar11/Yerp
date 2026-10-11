import { Button } from '@/components/ui'
import { useAnomalies } from '@/api/payroll'
import { formatINR } from '@/lib/utils'

/** Payslips that moved more than a fifth from the last period, found on request. */
export function Anomalies() {
  const q = useAnomalies()
  const d = q.data
  return (
    <section aria-label="Payroll anomalies" className="mt-8 rounded-xl border border-border bg-card p-4 shadow-card">
      <div className="flex items-center justify-between gap-3">
        <div><h2 className="text-sm font-semibold">Unusual payslips</h2><p className="text-xs text-muted-foreground">Payslips that differ by more than 20% from the previous period.</p></div>
        <Button size="sm" variant="outline" loading={q.isFetching} onClick={() => void q.refetch()}>Check now</Button>
      </div>
      {q.isError && <p role="alert" className="mt-3 text-[13px] text-danger">Could not check.</p>}
      {d && (d.anomalies.length === 0 ? <p className="mt-3 text-sm text-success">Nothing unusual across {d.total_checked} employees.</p> : (
        <ul className="mt-3 grid gap-2">
          {d.anomalies.map((a, i) => (
            <li key={i} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-sm last:border-0">
              <span><strong>{a.employee_name}</strong> <span className="text-muted-foreground">{formatINR(a.previous_net)} to {formatINR(a.current_net)}</span></span>
              <span className={a.direction === 'increased' ? 'font-semibold text-success' : 'font-semibold text-danger'}>{a.change_pct}%</span>
            </li>
          ))}
        </ul>
      ))}
    </section>
  )
}
