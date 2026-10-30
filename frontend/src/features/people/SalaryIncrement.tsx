import { useState } from 'react'
import { TrendingUp } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Field, Input, Modal, NumField, Select, Skeleton } from '@/components/ui'
import { giveIncrement, peopleKeys, updateEmployee, showEmployeeChange, useSalaryHistory, type EmployeeDetail } from '@/api/people'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'

/** The same day a year later, as a date string. */
const aYearOn = (d: string) => { const x = new Date(`${d}T00:00:00`); if (isNaN(+x)) return ''; x.setFullYear(x.getFullYear() + 1); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}` }
const amount = (n: number) => n.toLocaleString('en-IN', { maximumFractionDigits: 2 })

/** Raises the monthly salary and keeps the change; with the list of every increment so far. HR and the Master only. */
export function SalaryIncrement({ e }: { e: EmployeeDetail }) {
  const [open, setOpen] = useState(false)
  return (
    <section aria-label="Salary increments" className="mt-8">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Salary increments</h3>
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}><TrendingUp /> Give increment</Button>
      </div>
      <History id={e.id} />
      {open && <IncrementModal e={e} onClose={() => setOpen(false)} />}
    </section>
  )
}

function History({ id }: { id: number }) {
  const q = useSalaryHistory(id)
  if (q.isPending) return <Skeleton className="h-10 w-full" />
  const rows = q.data?.revisions ?? []
  if (!rows.length) return <p className="text-[13px] text-muted-foreground">No increments recorded yet.</p>
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-left text-[13px] text-muted-foreground">
          <tr><th className="px-3 py-2 font-medium">From</th><th className="px-3 py-2 font-medium">Until</th><th className="px-3 py-2 font-medium">Was</th><th className="px-3 py-2 font-medium">Became</th><th className="px-3 py-2 font-medium">Raise</th><th className="px-3 py-2 font-medium">Reason</th><th className="px-3 py-2 font-medium">By</th></tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="px-3 py-2">{r.effective_date}</td><td className="px-3 py-2">{r.valid_until}</td><td className="px-3 py-2">{amount(r.old_salary)}</td><td className="px-3 py-2 font-medium">{amount(r.new_salary)}</td>
              <td className="px-3 py-2">{r.percent}%</td><td className="px-3 py-2">{r.reason || '—'}</td><td className="px-3 py-2">{r.changed_by}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Nobody can be given a raise on no salary: the first one is set here, then increments follow. */
function FirstSalary({ e, onClose }: { e: EmployeeDetail; onClose: () => void }) {
  const qc = useQueryClient()
  const [salary, setSalary] = useState(0)
  const save = useAction(() => updateEmployee(e.id, { salary }), {
    success: 'Monthly salary set',
    onSuccess: (r) => { showEmployeeChange(qc, { saved: r }); onClose() },
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="md" title="Set the monthly salary" description={`${e.full_name} has no monthly salary yet, so there is nothing to raise. Set it first; increments follow from there.`}>
      <Field label="Monthly salary" htmlFor="si-first"><NumField id="si-first" value={salary} onValue={setSalary} /></Field>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!(salary > 0)} onClick={() => save.mutate()}>Set salary</Button>
      </div>
    </Modal>
  )
}

function IncrementModal({ e, onClose }: { e: EmployeeDetail; onClose: () => void }) {
  if (!(e.salary > 0)) return <FirstSalary e={e} onClose={onClose} />
  return <RaiseModal e={e} onClose={onClose} />
}

function RaiseModal({ e, onClose }: { e: EmployeeDetail; onClose: () => void }) {
  const qc = useQueryClient()
  const [mode, setMode] = useState<'percent' | 'amount'>('percent')
  const [value, setValue] = useState(0)
  const [date, setDate] = useState(today())
  const [reason, setReason] = useState('')
  // Runs a year unless HR picks another day; follows the start date until HR does.
  const [until, setUntil] = useState<string | null>(null)
  const runsTo = until ?? aYearOn(date)
  const next = mode === 'percent' ? Math.round(e.salary * (1 + value / 100) * 100) / 100 : value
  const save = useAction(() => giveIncrement(e.id, { mode, value, effective_date: date, valid_until: runsTo, reason }), {
    success: (r) => r.message,
    onSuccess: (r) => {
      showEmployeeChange(qc, { patch: { id: e.id, salary: r.salary } })
      qc.setQueryData<EmployeeDetail>(['people', 'employee', e.id], (old) => old && { ...old, salary: r.salary })
      void qc.invalidateQueries({ queryKey: [...peopleKeys.all, 'salary-history', e.id] })
      onClose()
    },
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="md" title="Give increment" description={`${e.full_name} is on ${amount(e.salary)} a month. Payslips made from the date it takes effect use the new salary; payslips already made keep theirs.`}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Give it as" htmlFor="si-mode"><Select id="si-mode" value={mode} onChange={(ev) => { setMode(ev.target.value as 'percent' | 'amount'); setValue(0) }} options={[{ value: 'percent', label: 'A percentage rise' }, { value: 'amount', label: 'A new monthly salary' }]} /></Field>
        <Field label={mode === 'percent' ? 'Percentage' : 'New monthly salary'} htmlFor="si-value"><NumField id="si-value" value={value} onValue={setValue} /></Field>
        <Field label="Takes effect on" htmlFor="si-date" hint="Today or an earlier day."><Input id="si-date" type="date" max={today()} value={date} onChange={(ev) => setDate(ev.target.value)} /></Field>
        <Field label="Valid until" htmlFor="si-until" hint="HR is reminded on this day to review it again."><Input id="si-until" type="date" min={date} value={runsTo} onChange={(ev) => setUntil(ev.target.value)} /></Field>
        <Field label="Reason" htmlFor="si-reason"><Input id="si-reason" value={reason} onChange={(ev) => setReason(ev.target.value)} placeholder="Annual appraisal" /></Field>
      </div>
      {value > 0 && <p className="mt-4 text-sm">New salary: <strong>{amount(next)}</strong> a month ({amount(next - e.salary)} more).</p>}
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!(value > 0) || !date || !runsTo || runsTo <= date} onClick={() => save.mutate()}>Give increment</Button>
      </div>
    </Modal>
  )
}
