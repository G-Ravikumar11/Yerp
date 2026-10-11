import { useState } from 'react'
import { Play, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button } from '@/components/ui'
import { usePayslips, type PayslipRow } from '@/api/payroll'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { PayslipFormModal } from './PayslipFormModal'
import { PayslipModal } from './PayslipModal'
import { Anomalies } from './Anomalies'
import { RunPayrollModal } from './RunPayrollModal'

export default function PayrollPage() {
  const q = usePayslips()
  const [open, setOpen] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const [running, setRunning] = useState(false)
  const rows = q.data ?? []
  const filters = useListFilters(rows, { search: (p) => [p.number, p.employee_name, p.status].join(' '), status: (p) => p.status, date: (p) => p.pay_date || p.period_end })
  const columns: TableColumn<PayslipRow>[] = [
    { id: 'no', header: 'Number', sort: (p) => p.number, cell: (p) => <button type="button" className="font-mono text-[13px] font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setOpen(p.id)}>{p.number}</button> },
    { id: 'who', header: 'Employee', sort: (p) => p.employee_name, cell: (p) => p.employee_name || '-' },
    { id: 'period', header: 'Period', hideBelow: 'lg', cell: (p) => `${formatDate(p.period_start)} to ${formatDate(p.period_end)}` },
    { id: 'paid', header: 'Pay date', hideBelow: 'xl', sort: (p) => p.pay_date, cell: (p) => formatDate(p.pay_date) || '-' },
    { id: 'gross', header: 'Gross', hideBelow: 'md', align: 'right', sort: (p) => p.gross_pay, cell: (p) => formatINR(p.gross_pay) },
    { id: 'ded', header: 'Deductions', hideBelow: 'lg', align: 'right', cell: (p) => formatINR(p.total_deductions) },
    { id: 'net', header: 'Net pay', align: 'right', sort: (p) => p.net_pay, cell: (p) => <strong>{formatINR(p.net_pay)}</strong> },
    { id: 'status', header: 'Status', cell: (p) => <div className="flex gap-1.5"><Badge tone={p.status === 'Paid' ? 'success' : p.status === 'Sent' ? 'info' : 'neutral'} dot>{p.status}</Badge>{p.sent && p.status !== 'Sent' && <Badge tone="info">Emailed</Badge>}</div> },
  ]
  return (
    <>
      <PageHeader eyebrow="People" title="Payroll" description="Payslips and payment. Run everyone's at once, or write one for a single person." actions={<><Button variant="outline" onClick={() => setRunning(true)}><Play /> Run payroll</Button><Button onClick={() => setCreating(true)}><Plus /> New payslip</Button></>} />
      <FilterBar filters={filters} placeholder="Search by number, employee or status..." />
      <DataTable label="Payslips" rows={filters.filtered} columns={columns} rowKey={(p) => p.id} onRowClick={(p) => setOpen(p.id)} loading={q.isPending} empty={filters.active ? 'Nothing matches those filters.' : 'No payslips yet. Run payroll to create one for everybody.'} />
      <Anomalies />
      <PayslipModal id={open} onClose={() => setOpen(null)} />
      <PayslipFormModal open={creating} onClose={() => setCreating(false)} />
      <RunPayrollModal open={running} onClose={() => setRunning(false)} />
    </>
  )
}
