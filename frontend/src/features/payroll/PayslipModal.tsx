import { useEffect, useState } from 'react'
import { Download, Mail, Printer } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Modal, NumField, Skeleton } from '@/components/ui'
import { deletePayslip, emailPayslip, markPaid, payKeys, payslipFile, reapplyStructure, reopenPayslip, savePayslipLines, usePayslip } from '@/api/payroll'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { payslipHtml, printPayslip } from './print'

export function PayslipModal({ id, onClose }: { id: number | null; onClose: () => void }) {
  const q = usePayslip(id)
  const p = q.data
  const [deleting, setDeleting] = useState(false)
  // The amounts on the payslip's own lines, as they are being typed.
  const [amounts, setAmounts] = useState<Record<number, number>>({})
  useEffect(() => { setAmounts(Object.fromEntries((p?.lines ?? []).map((l) => [l.id, l.amount]))) }, [p])
  const refresh = { invalidate: [payKeys.all] }
  const pay = useAction(() => markPaid(id as number), { ...refresh, success: 'Marked as paid' })
  const reopen = useAction(() => reopenPayslip(id as number), { ...refresh, success: 'Payslip reopened' })
  const saveLines = useAction(() => savePayslipLines(id as number, (p?.lines ?? []).map((l) => ({ id: l.id, amount: amounts[l.id] ?? l.amount }))), { ...refresh, success: 'Amounts saved' })
  const refill = useAction(() => reapplyStructure(id as number), { ...refresh, success: 'Brought up to date with the salary structure' })
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
          {!!p.lines?.length && p.status !== 'Paid' && (
            <section aria-label="Pay components" className="mt-5 rounded-lg border border-border p-4">
              <h3 className="text-sm font-semibold">Pay components</h3>
              <p className="mb-3 mt-1 text-[13px] text-muted-foreground">Worked out from the salary structure when this payslip was made. Type the ones that have no formula, or change any amount, then save.</p>
              <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                {p.lines.map((l) => (
                  <label key={l.id} className="block text-[13px]">
                    <span className="mb-1 block text-muted-foreground">{l.name} <span className="text-[11px]">({l.kind === 'earning' ? 'earning' : 'deduction'}{l.basis === 'percent' ? `, ${l.percent}%` : ', typed'})</span></span>
                    <NumField aria-label={l.name} value={amounts[l.id] ?? l.amount} onValue={(n) => setAmounts((a) => ({ ...a, [l.id]: n }))} />
                  </label>
                ))}
              </div>
              <div className="mt-4 flex flex-wrap justify-end gap-2">
                <Button variant="ghost" loading={refill.isPending} onClick={() => refill.mutate()}>Fill again from the structure</Button>
                <Button loading={saveLines.isPending} onClick={() => saveLines.mutate()}>Save amounts</Button>
              </div>
            </section>
          )}
          <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
            <Button variant="ghost" className="mr-auto text-danger" onClick={() => setDeleting(true)}>Delete</Button>
            <Button variant="outline" onClick={() => printPayslip(p)}><Printer /> Print</Button>
            <Button variant="outline" asChild><a href={payslipFile(p.id, 'pdf')}><Download /> PDF</a></Button>
            <Button variant="outline" asChild><a href={payslipFile(p.id, 'xlsx')}><Download /> Excel</a></Button>
            <Button variant="outline" loading={mail.isPending} onClick={() => mail.mutate()}><Mail /> {p.sent ? 'Email again' : 'Email to employee'}</Button>
            {p.status === 'Paid' ? <Button variant="outline" loading={reopen.isPending} onClick={() => reopen.mutate()}>Reopen</Button> : <Button loading={pay.isPending} onClick={() => pay.mutate()}>Mark as paid</Button>}
          </div>
          <ConfirmDialog open={deleting} onOpenChange={setDeleting} title={`Delete ${p.number}?`} description={p.status === 'Paid' ? 'This payslip is marked as paid. Deleting it anyway removes the record of that payment.' : 'The payslip is removed.'} confirmLabel="Delete it" tone="danger" loading={remove.isPending} onConfirm={() => remove.mutate(p.status === 'Paid')} />
        </div>
      )}
    </Modal>
  )
}
