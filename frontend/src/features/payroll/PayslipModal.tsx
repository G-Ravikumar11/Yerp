import { useState } from 'react'
import { Mail, Printer } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Modal, Skeleton } from '@/components/ui'
import { deletePayslip, emailPayslip, markPaid, payKeys, reopenPayslip, usePayslip } from '@/api/payroll'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { payslipHtml, printPayslip } from './print'

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
    <Modal open={id !== null} onOpenChange={(o) => !o && onClose()} title={p ? `Payslip ${p.number}` : 'Payslip'} description={p ? `${p.employee.full_name} - ${formatDate(p.period_start)} to ${formatDate(p.period_end)}` : undefined} size="xl">
      {!p ? <Skeleton className="h-64 w-full" /> : (
        <div>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            <Badge tone={p.status === 'Paid' ? 'success' : 'neutral'} dot>{p.status}</Badge>
            {p.sent && <Badge tone="info">Emailed</Badge>}
            <span className="text-muted-foreground">{p.employee.job_title}{p.employee.department_name && ` - ${p.employee.department_name}`} - pay date {formatDate(p.pay_date) || 'not set'}</span>
          </div>
          <iframe title={`Payslip ${p.number}`} srcDoc={payslipHtml(p)} className="h-[620px] w-full rounded-lg border border-border bg-white" />
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
