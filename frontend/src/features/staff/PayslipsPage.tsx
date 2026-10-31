import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge } from '@/components/ui'
import { useMyDashboard, type Payslip } from '@/api/staff'
import { financialYears, myForm16Pdf, payslipTone } from '@/api/payroll'
import { useState } from 'react'
import { Button, Select } from '@/components/ui'
import { Download } from 'lucide-react'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

/** The last six payslips the person has been given. */
export default function PayslipsPage() {
  const q = useMyDashboard()
  const years = financialYears()
  const [fy, setFy] = useState(years[0])
  const columns: TableColumn<Payslip>[] = [
    { id: 'no', header: 'Payslip', cell: (p) => <span className="font-mono text-[13px] font-semibold">{p.number}</span> },
    { id: 'period', header: 'Period', cell: (p) => `${formatDate(p.period_start)} to ${formatDate(p.period_end)}` },
    { id: 'paid', header: 'Pay date', hideBelow: 'md', cell: (p) => formatDate(p.pay_date) || '-' },
    { id: 'net', header: 'Net pay', align: 'right', cell: (p) => formatINR(p.net_pay) },
    // Only payslips released to them come here: paid, or issued (sent, or in a month HR has approved).
    { id: 'status', header: 'Status', cell: (p) => <Badge tone={payslipTone(p.status) === 'success' ? 'success' : 'neutral'}>{p.status.toLowerCase() === 'paid' ? 'Paid' : 'Issued'}</Badge> },
    { id: 'pdf', header: '', align: 'right', cell: (p) => <a href={`/api/employee/payslips/${p.id}/pdf`} download className="text-[13px] font-medium text-primary hover:underline" aria-label={`Download payslip ${p.number} as a PDF`}>PDF</a> },
  ]
  return (
    <>
      <PageHeader eyebrow="My work" title="Payslips" description="Your most recent six." actions={<div className="flex items-end gap-2"><div className="w-32"><Select aria-label="Financial year" value={fy} onChange={(e) => setFy(e.target.value)} options={years.map((y) => ({ value: y, label: `FY ${y}` }))} /></div><Button variant="outline" asChild><a href={myForm16Pdf(fy)} download><Download /> Form 16</a></Button></div>} />
      <DataTable label="Payslips" rows={q.data?.payslips ?? []} columns={columns} rowKey={(p) => p.id} loading={q.isPending} empty="No payslips yet. They appear here once HR has issued them." />
    </>
  )
}
