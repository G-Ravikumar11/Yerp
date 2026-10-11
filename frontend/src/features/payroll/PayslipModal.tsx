import { useState } from 'react'
import { Mail, Printer } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Modal, Skeleton } from '@/components/ui'
import { deletePayslip, emailPayslip, markPaid, payKeys, reopenPayslip, usePayslip, type PayslipDetail } from '@/api/payroll'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { printPayslip } from './print'

const earnings = (p: PayslipDetail): [string, number][] => [
  ['Basic pay', p.basic_salary],
  [`Overtime${p.overtime_hours ? ` (${p.overtime_hours}h)` : ''}`, p.overtime_pay],
  ['Bonus', p.bonus],
  ['Allowances', p.allowances],
]
const deductions = (p: PayslipDetail): [string, number][] => [
  ['Tax', p.tax_amount],
  ['Insurance', p.insurance],
  ['Retirement / PF', p.retirement],
  ['Other deductions', p.other_deductions],
  ...(p.standing_deduction > 0 ? ([['Standing deduction', p.standing_deduction]] as [string, number][]) : []),
]

function Breakdown({ title, rows, total, totalLabel }: { title: string; rows: [string, number][]; total: number; totalLabel: string }) {
  return (
    <section aria-label={title}>
      <h3 className="mb-1.5 text-sm font-semibold">{title}</h3>
      <dl className="grid gap-1 text-sm">
        {rows.map(([l, v]) => <div key={l} className="flex justify-between"><dt className="text-muted-foreground">{l}</dt><dd className="tabular">{formatINR(v)}</dd></div>)}
        <div className="flex justify-between border-t border-border pt-1 font-semibold"><dt>{totalLabel}</dt><dd className="tabular">{formatINR(total)}</dd></div>
      </dl>
    </section>
  )
}

export function PayslipModal({ id, onClose }: { id: number | null; onClose: () => void }) {
  const q = usePayslip(id)
  const p = q.data
  const [deleting, setDeleting] = useState(false)
  const refresh = { invalidate: [payKeys.all] }
  const pay = useAction(() => markPaid(id as number), { ...refresh, success: 'Marked as paid' })
  const reopen = useAction(() => reopenPayslip(id as number), { ...refresh, success: 'Payslip reopened' })
  const mail = useAction(() => emailPayslip(id as number), { ...refresh, success: (r) => r.message || 'Payslip emailed' })
  const remove = useAction((force: boolean) => deletePayslip(id as number, force), { invalidate: [['payroll', 'list']], success: 'Payslip deleted', onSuccess: () => { setDeleting(false); onClose() } })
  return (
    <Modal open={id !== null} onOpenChange={(o) => !o && onClose()} title={p ? `Payslip ${p.number}` : 'Payslip'} description={p ? `${p.employee.full_name} - ${formatDate(p.period_start)} to ${formatDate(p.period_end)}` : undefined} size="lg">
      {!p ? <Skeleton className="h-64 w-full" /> : (
        <div>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            <Badge tone={p.status === 'Paid' ? 'success' : 'neutral'} dot>{p.status}</Badge>
            {p.sent && <Badge tone="info">Emailed</Badge>}
            <span className="text-muted-foreground">{p.employee.job_title}{p.employee.department_name && ` - ${p.employee.department_name}`} - pay date {formatDate(p.pay_date) || 'not set'}</span>
          </div>
          <div className="grid gap-6 sm:grid-cols-2">
            <Breakdown title="Earnings" rows={earnings(p)} total={p.gross_pay} totalLabel="Gross" />
            <Breakdown title="Deductions" rows={deductions(p)} total={p.total_deductions} totalLabel="Total deductions" />
          </div>
          <p className="mt-4 flex items-baseline justify-between rounded-lg bg-primary-soft px-4 py-3"><span className="text-sm font-medium">Net pay</span><span className="tabular font-display text-2xl font-semibold">{formatINR(p.net_pay)}</span></p>
          {(p.employee.bank_name || p.employee.bank_account) && <p className="mt-3 text-[13px] text-muted-foreground">Paid to {p.employee.bank_name} {p.employee.bank_account}</p>}
          {p.notes && <p className="mt-2 text-[13px]">{p.notes}</p>}
          <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
            <Button variant="ghost" className="mr-auto text-danger" onClick={() => setDeleting(true)}>Delete</Button>
            <Button variant="outline" onClick={() => printPayslip(p)}><Printer /> Print</Button>
            <Button variant="outline" loading={mail.isPending} onClick={() => mail.mutate()}><Mail /> {p.sent ? 'Email again' : 'Email to employee'}</Button>
            {p.status === 'Paid' ? <Button variant="outline" loading={reopen.isPending} onClick={() => reopen.mutate()}>Reopen</Button> : <Button loading={pay.isPending} onClick={() => pay.mutate()}>Mark as paid</Button>}
          </div>
          <ConfirmDialog open={deleting} onOpenChange={setDeleting} title={`Delete ${p.number}?`} description={p.status === 'Paid' ? 'This payslip is marked as paid. Deleting it anyway removes the record of that payment.' : 'The payslip is removed.'} confirmLabel="Delete it" tone="danger" loading={remove.isPending} onConfirm={() => remove.mutate(p.status === 'Paid')} />
        </div>
      )}
    </Modal>
  )
}
