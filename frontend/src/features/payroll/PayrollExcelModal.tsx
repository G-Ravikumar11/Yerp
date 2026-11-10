import { useState } from 'react'
import { Download } from 'lucide-react'
import { Badge, Button, Field, Input, Modal } from '@/components/ui'
import { payrollDatesFile, payrollMonthFile, usePayrollMonths, usePayslips } from '@/api/payroll'
import { plural } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const label = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleString('en-IN', { month: 'long', year: 'numeric' })

/** Every month with payslips kept, one file each; or a stretch of months, picked by from and to, in a single file. */
export function PayrollExcelModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Download payroll Excel" size="lg" description="Each month's payslips are kept as their own file. Download one month, or choose a period to get those months together, with a line a month on a second sheet.">
      {open && <Months />}
    </Modal>
  )
}

function Months() {
  const q = usePayrollMonths()
  const slips = usePayslips()
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const bad = !!from && !!to && to < from
  const all = (q.data ?? []).filter((m) => (m.payslips ?? 0) > 0)
  // A month is listed when any of its days is inside the dates picked.
  const shown = all.filter((m) => (!from || `${m.month}-31` >= from) && (!to || `${m.month}-01` <= to))
  // The payslips the dates pick: by the day each is paid, the date the Payroll list filters on too.
  const picked = (slips.data ?? []).filter((p) => p.status !== 'Void' && (!from || (p.pay_date || p.period_end) >= from) && (!to || (p.pay_date || p.period_end) <= to))
  const net = picked.reduce((t, p) => t + p.net_pay, 0)
  const ranged = !!from || !!to
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="From date" htmlFor="px-from"><Input id="px-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="To date" htmlFor="px-to" error={bad ? 'The end date is before the start.' : undefined}><Input id="px-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
      </div>
      <div className="mt-4 max-h-[45vh] overflow-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-card text-left text-[12px] text-muted-foreground"><tr><th className="px-3 py-2">Month</th><th>Status</th><th className="text-right">Payslips</th><th className="text-right">Net pay</th><th className="px-3" /></tr></thead>
          <tbody>
            {q.isPending && <tr><td colSpan={5} className="px-3 py-4 text-muted-foreground">Loading months...</td></tr>}
            {!q.isPending && !shown.length && <tr><td colSpan={5} className="px-3 py-4 text-muted-foreground">{all.length ? 'No month with payslips between those dates.' : 'No payslips yet. Run payroll to create some.'}</td></tr>}
            {shown.map((m) => (
              <tr key={m.month} className="border-t border-border">
                <td className="px-3 py-2 font-medium">{label(m.month)}</td>
                <td><Badge tone={m.status === 'Draft' ? 'warning' : 'neutral'} dot>{m.status}</Badge></td>
                <td className="text-right">{m.payslips}</td>
                <td className="text-right">{formatINR(m.net_pay ?? 0)}</td>
                <td className="px-3 py-1.5 text-right"><Button size="sm" variant="outline" asChild><a href={payrollMonthFile(m.month)}><Download /> Excel</a></Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-4">
        <span className="text-sm text-muted-foreground">{ranged ? <>{plural(picked.length, 'payslip')} paid between these dates, net <strong className="text-foreground">{formatINR(net)}</strong></> : 'Pick dates to download only the payslips paid between them.'}</span>
        <Button asChild disabled={!ranged || bad || !picked.length}>
          <a href={payrollDatesFile(from, to)} aria-disabled={!ranged || bad || !picked.length}><Download /> Download this period</a>
        </Button>
      </div>
    </div>
  )
}
