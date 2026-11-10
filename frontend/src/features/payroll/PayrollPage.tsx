import { useState } from 'react'
import { Download, ListChecks, Play, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button } from '@/components/ui'
import { payKeys, payslipTone, setAutoPayroll, useAutoPayroll, usePayslips, type PayslipRow } from '@/api/payroll'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { PayslipFormModal } from './PayslipFormModal'
import { PayslipModal } from './PayslipModal'
import { Anomalies } from './Anomalies'
import { MonthPanel } from './MonthPanel'
import { PayrollExcelModal } from './PayrollExcelModal'
import { RunPayrollModal } from './RunPayrollModal'
import { SalaryStructureModal } from './SalaryStructureModal'

/** Whether the month's payslips draft themselves on the 1st. Anybody can see it; the Master changes it. */
function AutoPayroll() {
  const { can } = useSession()
  const canManage = can('people.manage')
  const q = useAutoPayroll()
  const set = useAction((on: boolean) => setAutoPayroll(on), { invalidate: [payKeys.all], success: (r) => r.message })
  const on = q.data?.enabled ?? true
  return (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium">Automatic monthly payroll</p>
        <p className="text-[13px] text-muted-foreground">{on ? "On. When a month ends, everyone's payslip for it is drafted for you to review and pay." : 'Off. Payslips are only created when you run payroll yourself.'}</p>
      </div>
      <button type="button" role="switch" aria-checked={on} aria-label="Automatic monthly payroll" disabled={!canManage || q.isPending || set.isPending} onClick={() => set.mutate(!on)}
        className={'relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 ' + (on ? 'bg-[var(--primary)]' : 'bg-muted-foreground/30')}>
        <span className={'absolute top-0.5 size-4 rounded-full bg-white transition-all ' + (on ? 'left-[18px]' : 'left-0.5')} />
      </button>
    </div>
  )
}

export default function PayrollPage() {
  const q = usePayslips()
  const [open, setOpen] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const [running, setRunning] = useState(false)
  const [structure, setStructure] = useState(false)
  const [excel, setExcel] = useState(false)
  const rows = q.data ?? []
  const filters = useListFilters(rows, { search: (p) => [p.number, p.employee_name, p.status].join(' '), status: (p) => p.status, date: (p) => p.pay_date || p.period_end })
  const columns: TableColumn<PayslipRow>[] = [
    { id: 'no', header: 'Number', sort: (p) => p.number, cell: (p) => <button type="button" className="font-mono text-[13px] font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setOpen(p.id)}>{p.number}</button> },
    { id: 'who', header: 'Employee', sort: (p) => p.employee_name, cell: (p) => p.employee_name || '-' },
    { id: 'period', header: 'Period', hideBelow: 'lg', cell: (p) => `${formatDate(p.period_start)} to ${formatDate(p.period_end)}` },
    { id: 'paid', header: 'Pay date', hideBelow: 'xl', sort: (p) => p.pay_date, cell: (p) => formatDate(p.pay_date) || '-' },
    { id: 'gross', header: 'Gross', hideBelow: 'md', align: 'right', sort: (p) => p.gross_pay, cell: (p) => formatINR(p.gross_pay) },
    { id: 'ded', header: 'Deductions', hideBelow: 'lg', align: 'right', cell: (p) => formatINR(p.total_deductions) },
    // The statutory breakdown. Employer PF is EPF and EPS together; ESI shows the person's share and the company's.
    { id: 'pf', header: 'Employee PF', hideBelow: 'xl', align: 'right', sort: (p) => p.employee_pf ?? 0, cell: (p) => formatINR(p.employee_pf ?? 0) },
    { id: 'epf', header: 'Employer PF', hideBelow: 'xl', align: 'right', cell: (p) => <span title={`EPF ${formatINR(p.employer_epf ?? 0)} + EPS ${formatINR(p.employer_eps ?? 0)}`}>{formatINR(p.employer_pf ?? 0)}</span> },
    { id: 'esi', header: 'ESI (employee + employer)', hideBelow: 'xl', align: 'right', cell: (p) => (p.employee_esi || p.employer_esi) ? `${formatINR(p.employee_esi ?? 0)} + ${formatINR(p.employer_esi ?? 0)}` : '-' },
    { id: 'pt', header: 'PT', hideBelow: 'xl', align: 'right', cell: (p) => formatINR(p.professional_tax ?? 0) },
    { id: 'lop', header: 'LOP days', hideBelow: 'lg', align: 'right', sort: (p) => p.lop_days ?? 0, cell: (p) => (p.working_days ? p.lop_days ?? 0 : '-') },
    { id: 'days', header: 'Paid days', hideBelow: 'lg', align: 'right', cell: (p) => (p.working_days ? `${p.paid_days ?? 0} / ${p.working_days}` : '-') },
    { id: 'net', header: 'Net pay', align: 'right', sort: (p) => p.net_pay, cell: (p) => <strong>{formatINR(p.net_pay)}</strong> },
    { id: 'status', header: 'Status', cell: (p) => <div className="flex gap-1.5"><Badge tone={payslipTone(p.status)} dot>{p.status}</Badge>{p.sent && p.status.toLowerCase() !== 'sent' && <Badge tone="info">Emailed</Badge>}{p.month_status === 'Locked' && <Badge tone="neutral">Locked</Badge>}</div> },
  ]
  return (
    <>
      <PageHeader eyebrow="People" title="Payroll" description="Payslips and payment. Run everyone's at once, or write one for a single person." actions={<><Button variant="outline" onClick={() => setExcel(true)} title="Every stored month, or a period of your choice"><Download /> Excel</Button><Button variant="outline" onClick={() => setStructure(true)}><ListChecks /> Salary structure</Button><Button variant="outline" onClick={() => setRunning(true)}><Play /> Run payroll</Button><Button onClick={() => setCreating(true)}><Plus /> New payslip</Button></>} />
      <AutoPayroll />
      <MonthPanel />
      <FilterBar filters={filters} placeholder="Search by number, employee or status..." />
      <DataTable label="Payslips" rows={filters.filtered} columns={columns} rowKey={(p) => p.id} onRowClick={(p) => setOpen(p.id)} loading={q.isPending} empty={filters.active ? 'Nothing matches those filters.' : 'No payslips yet. Run payroll to create one for everybody.'} />
      <Anomalies />
      <PayslipModal id={open} onClose={() => setOpen(null)} />
      <PayslipFormModal open={creating} onClose={() => setCreating(false)} />
      <PayrollExcelModal open={excel} onClose={() => setExcel(false)} />
      <RunPayrollModal open={running} onClose={() => setRunning(false)} />
      <SalaryStructureModal open={structure} onClose={() => setStructure(false)} />
    </>
  )
}
