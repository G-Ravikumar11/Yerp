import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button, Field, Input, Modal } from '@/components/ui'
import { payKeys, runPayroll, type RunResult } from '@/api/payroll'
import { useAction } from '@/lib/mutate'
import { plural, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const monthStart = () => today().slice(0, 8) + '01'

/** Payroll for every active person in one go, worked hours included. Anyone already paid for the period is skipped. */
export function RunPayrollModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Run payroll for everyone" description="One payslip for each person still on the books, worked out from their salary and attendance. Anyone who already has one covering the period is skipped.">
      {open && <Form onClose={onClose} />}
    </Modal>
  )
}

function Form({ onClose }: { onClose: () => void }) {
  const [start, setStart] = useState(monthStart())
  const [end, setEnd] = useState(today())
  const [payDate, setPayDate] = useState(today())
  const [result, setResult] = useState<RunResult | null>(null)
  const run = useAction(() => runPayroll({ period_start: start, period_end: end, pay_date: payDate }), {
    invalidate: [payKeys.all],
    success: (r) => `${plural(r.created.length, 'payslip')} created, net ${formatINR(r.total_net)}${r.skipped.length ? `; ${r.skipped.length} skipped (already paid for this period)` : ''}`,
    onSuccess: (r) => { if (r.warnings?.length) setResult(r); else onClose() },
  })
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
        {run.error && <p role="alert" className="mr-auto text-[13px] text-danger">{run.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={run.isPending} disabled={!start || !end || !payDate} onClick={() => run.mutate()}>Run payroll</Button>
      </div>
    </div>
  )
}
