import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button, Field, Input, Modal } from '@/components/ui'
import { payKeys, previewPayroll, runPayroll, type PayrollPreview, type PreviewRow, type RunOverride, type RunResult } from '@/api/payroll'
import { useAction } from '@/lib/mutate'
import { plural, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const monthStart = () => today().slice(0, 8) + '01'

/** Payroll for every active person in one go, worked hours included. Anyone already paid for the period is skipped. */
export function RunPayrollModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Run payroll for everyone" size="xl" description="Preview what each person will be paid, change bonus, overtime or tax where needed, then create the payslips. Anyone who already has one covering the period is skipped.">
      {open && <Form onClose={onClose} />}
    </Modal>
  )
}

function Form({ onClose }: { onClose: () => void }) {
  const [start, setStart] = useState(monthStart())
  const [end, setEnd] = useState(today())
  const [payDate, setPayDate] = useState(today())
  const [result, setResult] = useState<RunResult | null>(null)
  const period = { period_start: start, period_end: end, pay_date: payDate }
  const [preview, setPreview] = useState<PayrollPreview | null>(null)
  const [edits, setEdits] = useState<Record<number, RunOverride>>({})
  const [left, setLeft] = useState<number[]>([])      // people taken out of this run
  const ids = preview?.rows.filter((r) => !left.includes(r.employee_id)).map((r) => r.employee_id)
  const look = useAction(() => previewPayroll(period, ids, edits), { onSuccess: setPreview })
  const first = useAction(() => previewPayroll(period), { onSuccess: (r) => { setPreview(r); setEdits({}); setLeft([]) } })
  const run = useAction(() => runPayroll(period, ids, edits), {
    invalidate: [payKeys.all],
    success: (r) => `${plural(r.created.length, 'payslip')} created, net ${formatINR(r.total_net)}${r.skipped.length ? `; ${r.skipped.length} skipped (already paid for this period)` : ''}`,
    onSuccess: (r) => { if (r.warnings?.length) setResult(r); else onClose() },
  })
  if (preview && !result) {
    const live = preview.rows.filter((r) => !left.includes(r.employee_id))
    const type = (id: number, key: keyof RunOverride, v: string) => setEdits((e) => ({ ...e, [id]: { ...e[id], [key]: v === '' ? undefined : Number(v) } }))
    const cell = (r: PreviewRow, key: keyof RunOverride) => (
      <Input aria-label={`${key} for ${r.name}`} type="number" min="0" className="h-8 w-24 text-right" value={edits[r.employee_id]?.[key] ?? r[key]} onChange={(e) => type(r.employee_id, key, e.target.value)} />
    )
    return (
      <div>
        <div className="max-h-[55vh] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card text-left text-[12px] text-muted-foreground"><tr>
              <th className="py-1.5">Person</th><th>Paid days</th><th className="text-right">Basic</th><th>Bonus</th><th>OT hrs</th><th>Tax</th><th className="text-right">Gross</th><th className="text-right">Net</th><th />
            </tr></thead>
            <tbody>{preview.rows.map((r) => {
              const out = left.includes(r.employee_id)
              return (
                <tr key={r.employee_id} className={out ? 'opacity-40' : ''}>
                  <td className="py-1">{r.name}</td>
                  <td>{r.paid_days ?? '-'}{r.lop_days ? ` (${r.lop_days} LOP)` : ''}</td>
                  <td className="text-right">{formatINR(r.basic_salary)}</td>
                  <td>{cell(r, 'bonus')}</td><td>{cell(r, 'overtime_hours')}</td><td>{cell(r, 'tax_amount')}</td>
                  <td className="text-right">{formatINR(r.gross_pay)}</td><td className="text-right font-semibold">{formatINR(r.net_pay)}</td>
                  <td><Button size="sm" variant="ghost" onClick={() => setLeft((l) => out ? l.filter((x) => x !== r.employee_id) : [...l, r.employee_id])}>{out ? 'Add back' : 'Leave out'}</Button></td>
                </tr>
              )
            })}</tbody>
          </table>
        </div>
        {preview.warnings.length > 0 && <p className="mt-2 text-[13px] text-warning">{preview.warnings.map((w) => w.name).join(', ')}: no salary and no hours, so the payslip would be zero.</p>}
        <p className="mt-2 text-[13px] text-muted-foreground">Change a figure, then press Recalculate to see the new gross and net.{preview.skipped.length ? ` ${preview.skipped.length} skipped (already paid for this period).` : ''}</p>
        <div className="mt-4 flex items-center justify-end gap-2 border-t border-border pt-4">
          {(run.error || look.error) && <p role="alert" className="text-[13px] text-danger">{(run.error || look.error)?.message}</p>}
          <span className="mr-auto text-sm">{plural(live.length, 'payslip')}, net <strong>{formatINR(live.reduce((t, r) => t + r.net_pay, 0))}</strong></span>
          <Button variant="ghost" onClick={() => setPreview(null)}>Back</Button>
          <Button variant="outline" loading={look.isPending} onClick={() => look.mutate()}>Recalculate</Button>
          <Button loading={run.isPending} disabled={!live.length} onClick={() => run.mutate()}>Create payslips</Button>
        </div>
      </div>
    )
  }
  if (result) {
    return (
      <div>
        <p className="mb-2 flex items-center gap-2 text-sm font-semibold"><AlertTriangle className="size-4 text-warning" /> Check these payslips before approving</p>
        <ul className="grid gap-1.5 text-sm">{result.warnings?.map((w) => <li key={w.number}><strong>{w.name}</strong> ({w.number}): {w.reason}</li>)}</ul>
        <p className="mt-2 text-[13px] text-muted-foreground">A payslip of nothing nearly always means missing hours. Open it from the list and correct it.</p>
        <div className="mt-5 flex justify-end border-t border-border pt-4"><Button onClick={onClose}>Done</Button></div>
      </div>
    )
  }
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Period from" htmlFor="pr-start"><Input id="pr-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="Period to" htmlFor="pr-end"><Input id="pr-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
        <Field label="Pay date" htmlFor="pr-pay"><Input id="pr-pay" type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {first.error && <p role="alert" className="mr-auto text-[13px] text-danger">{first.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={first.isPending} disabled={!start || !end || !payDate} onClick={() => first.mutate()}>Preview payroll</Button>
      </div>
    </div>
  )
}
