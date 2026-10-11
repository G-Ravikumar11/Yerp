import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge } from '@/components/ui'
import { useMyDashboard, type Payslip } from '@/api/staff'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

/** The last six payslips the person has been given. */
export default function PayslipsPage() {
  const q = useMyDashboard()
  const columns: TableColumn<Payslip>[] = [
    { id: 'no', header: 'Payslip', cell: (p) => <span className="font-mono text-[13px] font-semibold">{p.number}</span> },
    { id: 'period', header: 'Period', cell: (p) => `${formatDate(p.period_start)} to ${formatDate(p.period_end)}` },
    { id: 'paid', header: 'Pay date', hideBelow: 'md', cell: (p) => formatDate(p.pay_date) || '-' },
    { id: 'net', header: 'Net pay', align: 'right', cell: (p) => formatINR(p.net_pay) },
    { id: 'status', header: 'Status', cell: (p) => <Badge tone={p.status === 'paid' ? 'success' : 'neutral'}>{p.status.charAt(0).toUpperCase() + p.status.slice(1)}</Badge> },
  ]
  return (
    <>
      <PageHeader eyebrow="My work" title="Payslips" description="Your most recent six." />
      <DataTable label="Payslips" rows={q.data?.payslips ?? []} columns={columns} rowKey={(p) => p.number} loading={q.isPending} empty="No payslips yet. They appear here once payroll has been run." />
    </>
  )
}
