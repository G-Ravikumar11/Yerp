import { useEffect, useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { createPayslip, payKeys, usePayDetails } from '@/api/payroll'
import { useEmployees } from '@/api/people'
import { ApiError } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const monthStart = () => today().slice(0, 8) + '01'
const monthEnd = () => { const d = new Date(); return today().slice(0, 8) + String(new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()).padStart(2, '0') }

export function PayslipFormModal({ open, onClose, employeeId }: { open: boolean; onClose: () => void; employeeId?: number }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="New payslip" description="Pick the person and the period; salary, hours and overtime fill in from their record and their attendance." size="lg">
      {open && <Form employeeId={employeeId} onClose={onClose} />}
    </Modal>
  )
}

function Form({ employeeId, onClose }: { employeeId?: number; onClose: () => void }) {
  const people = useEmployees('')
  const [emp, setEmp] = useState(employeeId ? String(employeeId) : '')
  const [start, setStart] = useState(monthStart())
  const [end, setEnd] = useState(monthEnd())
  const [payDate, setPayDate] = useState(today())
  const [f, setF] = useState({ basic: 0, hours: 0, otHours: 0, otRate: 0, bonus: 0, allow: 0, insurance: 0, retirement: 0, other: 0 })
  const [notes, setNotes] = useState('')
  const [clash, setClash] = useState('')
  const details = usePayDetails(emp ? Number(emp) : null, start, end)
  const d = details.data
  useEffect(() => {
    if (d) setF((x) => ({ ...x, basic: d.salary || 0, hours: d.hours_worked || 0, otHours: d.overtime_hours || 0, otRate: d.overtime_rate || 0, bonus: d.bonus || 0, allow: d.allowances || 0 }))
  }, [d])
  const set = (k: keyof typeof f) => (n: number) => setF((x) => ({ ...x, [k]: n }))
  const otPay = f.otHours * f.otRate
  const gross = f.basic + otPay + f.bonus + f.allow
  const tax = Math.round(gross * ((d?.tax_rate ?? 0) / 100) * 100) / 100
  const deductions = (d?.deductions ?? 0) + f.insurance + f.retirement + f.other
  const net = Math.round((gross - tax - deductions) * 100) / 100
  const body = () => ({ employee_id: Number(emp), period_start: start, period_end: end, pay_date: payDate, hours_worked: f.hours, basic_salary: f.basic, overtime_hours: f.otHours, overtime_rate: f.otRate, bonus: f.bonus, allowances: f.allow, insurance: f.insurance, retirement: f.retirement, other_deductions: f.other, notes })
  const save = useAction((overlap: boolean) => createPayslip(body(), overlap), {
    invalidate: [payKeys.all, ['people']],
    success: (r) => r.message || 'Payslip created',
    onSuccess: onClose,
    // A payslip already covers the period: say so and let the owner knowingly go ahead.
    onError: (e) => { if (e instanceof ApiError && e.status === 409) setClash(e.message) },
  })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Employee" htmlFor="ps-emp" className="sm:col-span-3"><Select id="ps-emp" value={emp} placeholder="Choose an employee" onChange={(e) => { setEmp(e.target.value); setClash('') }} options={(people.data ?? []).map((e) => ({ value: e.id, label: e.full_name || `${e.first_name} ${e.last_name}` }))} /></Field>
        <Field label="Period from" htmlFor="ps-start"><Input id="ps-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="Period to" htmlFor="ps-end"><Input id="ps-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
        <Field label="Pay date" htmlFor="ps-pay"><Input id="ps-pay" type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} /></Field>
        <Field label="Basic pay" htmlFor="ps-basic" hint={d?.is_hourly ? 'Worked out from hours at the hourly rate' : undefined}><NumField id="ps-basic" value={f.basic} onValue={set('basic')} /></Field>
        <Field label="Hours worked" htmlFor="ps-hours"><NumField id="ps-hours" value={f.hours} onValue={set('hours')} /></Field>
        <span />
        <Field label="Overtime hours" htmlFor="ps-oth"><NumField id="ps-oth" value={f.otHours} onValue={set('otHours')} /></Field>
        <Field label="Overtime rate" htmlFor="ps-otr"><NumField id="ps-otr" value={f.otRate} onValue={set('otRate')} /></Field>
        <span />
        <Field label="Bonus" htmlFor="ps-bonus"><NumField id="ps-bonus" value={f.bonus} onValue={set('bonus')} /></Field>
        <Field label="Allowances" htmlFor="ps-allow"><NumField id="ps-allow" value={f.allow} onValue={set('allow')} /></Field>
        <span />
        <Field label="Insurance" htmlFor="ps-ins"><NumField id="ps-ins" value={f.insurance} onValue={set('insurance')} /></Field>
        <Field label="Retirement / PF" htmlFor="ps-ret"><NumField id="ps-ret" value={f.retirement} onValue={set('retirement')} /></Field>
        <Field label="Other deductions" htmlFor="ps-oth2"><NumField id="ps-oth2" value={f.other} onValue={set('other')} /></Field>
        <Field label="Notes" htmlFor="ps-notes" className="sm:col-span-3"><Textarea id="ps-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
      {emp && (
        <dl aria-label="Preview" className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1 rounded-lg bg-muted/50 p-3 text-sm sm:grid-cols-4">
          <div><dt className="text-xs text-muted-foreground">Gross</dt><dd className="tabular font-semibold">{formatINR(gross)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Tax{d ? ` (${d.tax_rate}%)` : ''}</dt><dd className="tabular font-semibold">{formatINR(tax)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Other deductions</dt><dd className="tabular font-semibold">{formatINR(deductions)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Net pay</dt><dd className="tabular font-display text-base font-semibold">{formatINR(net)}</dd></div>
        </dl>
      )}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {clash ? <p role="alert" className="mr-auto max-w-md text-[13px] text-warning">{clash}</p> : save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        {clash ? <Button loading={save.isPending} onClick={() => save.mutate(true)}>Create it anyway</Button> : <Button loading={save.isPending} disabled={!emp || !start || !end || !payDate} onClick={() => save.mutate(false)}>Create payslip</Button>}
      </div>
    </div>
  )
}
