import { useState } from 'react'
import { Download } from 'lucide-react'
import { Button, Field, Input, Modal, NumField, Select, Skeleton, Textarea } from '@/components/ui'
import { adjustLeave, financialYears, form16Pdf, payKeys, settlementPdf, useLeaveLedger, useSettlement } from '@/api/payroll'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'
import { today } from '@/lib/format'

const KIND_LABEL: Record<string, string> = { accrual: 'Accrued', carry_forward: 'Carried over', lapse: 'Lapsed', adjustment: 'Adjusted by HR' }

/** HR's tools for one person: the full and final settlement, their Form 16, and their leave ledger. */
export function EmployeePayTools({ id, endDate }: { id: number; endDate?: string }) {
  const [settling, setSettling] = useState(false)
  const [ledger, setLedger] = useState(false)
  const years = financialYears()
  const [fy, setFy] = useState(years[0])
  return (
    <section aria-label="Settlement, tax and leave" className="mt-6 border-t border-border pt-5">
      <h4 className="mb-3 text-sm font-semibold">Settlement, tax and leave</h4>
      <div className="flex flex-wrap items-end gap-3">
        <Button variant="outline" onClick={() => setSettling(true)}>Full and final settlement</Button>
        <div className="flex items-end gap-2">
          <div className="w-32"><Select aria-label="Financial year" value={fy} onChange={(e) => setFy(e.target.value)} options={years.map((y) => ({ value: y, label: `FY ${y}` }))} /></div>
          <Button variant="outline" asChild><a href={form16Pdf(id, fy)} download><Download /> Form 16</a></Button>
        </div>
        <Button variant="outline" onClick={() => setLedger(true)}>Leave ledger</Button>
      </div>
      <Modal open={settling} onOpenChange={setSettling} title="Full and final settlement" size="lg">{settling && <SettlementView id={id} endDate={endDate} />}</Modal>
      <Modal open={ledger} onOpenChange={setLedger} title="Leave ledger" size="lg">{ledger && <LedgerView id={id} />}</Modal>
    </section>
  )
}

function SettlementView({ id, endDate }: { id: number; endDate?: string }) {
  const [lastDay, setLastDay] = useState(endDate || today())
  const q = useSettlement(id, lastDay)
  const s = q.data
  return (
    <div>
      <Field label="Last working day" htmlFor="ff-last"><Input id="ff-last" type="date" value={lastDay} onChange={(e) => setLastDay(e.target.value)} /></Field>
      {q.isPending ? <Skeleton className="mt-4 h-40 w-full" /> : q.error ? <p role="alert" className="mt-4 text-sm text-danger">{q.error.message}</p> : s && (
        <>
          <p className="mt-4 text-[13px] text-muted-foreground">Joined {s.start_date || 'not recorded'}; {s.service.completed_years} year(s) completed. Last drawn basic {formatINR(s.last_basic)}.</p>
          <table className="mt-3 w-full text-sm">
            <tbody className="divide-y divide-border">
              {s.parts.map((p) => (
                <tr key={p.item}><td className="py-2 font-medium">{p.item}<div className="text-[12px] font-normal text-muted-foreground">{p.note}</div></td><td className="py-2 text-right tabular">{formatINR(p.amount)}</td></tr>
              ))}
              <tr><td className="py-2 font-semibold">Total payable</td><td className="py-2 text-right font-display text-base font-semibold tabular">{formatINR(s.total)}</td></tr>
            </tbody>
          </table>
          {s.arrears.rows.length > 0 && (
            <details className="mt-3 text-[13px]"><summary className="cursor-pointer text-muted-foreground">Arrears, payslip by payslip</summary>
              <ul className="mt-2 space-y-1">{s.arrears.rows.map((r) => <li key={r.payslip}>{r.payslip} ({r.period_end}): paid on {formatINR(r.paid_on_salary)}, now {formatINR(r.salary_now)} - {formatINR(r.amount)}</li>)}</ul>
            </details>
          )}
          <p className="mt-3 text-[12px] text-muted-foreground">PF, ESI and tax on these amounts are deducted when they are paid.</p>
          <div className="mt-4 flex justify-end"><Button variant="outline" asChild><a href={settlementPdf(id, lastDay)} download><Download /> PDF</a></Button></div>
        </>
      )}
    </div>
  )
}

function LedgerView({ id }: { id: number }) {
  const year = new Date().getFullYear()
  const q = useLeaveLedger(id, year)
  const [f, setF] = useState({ leave_type: 'annual', days: 0, note: '' })
  const save = useAction(() => adjustLeave(id, f), { invalidate: [payKeys.all, ['people']], success: (r) => r.message || 'Leave adjusted', onSuccess: () => setF((x) => ({ ...x, days: 0, note: '' })) })
  if (q.isPending || !q.data) return <Skeleton className="h-40 w-full" />
  const d = q.data
  return (
    <div>
      {!d.enabled && <p className="mb-3 rounded-md bg-muted/50 p-3 text-[13px] text-muted-foreground">Monthly accrual is off, so everybody has their whole year's leave from January. Turn it on from the Leave page.</p>}
      <p className="text-sm">{year}: annual {d.balance.annual_total} credited, {d.balance.annual_remaining} left; sick {d.balance.sick_total} credited, {d.balance.sick_remaining} left.</p>
      <table className="mt-3 w-full text-sm">
        <thead className="text-left text-[12px] text-muted-foreground"><tr><th className="py-1">Date</th><th>Leave</th><th>Entry</th><th className="text-right">Days</th><th className="pl-3">Note</th></tr></thead>
        <tbody className="divide-y divide-border">
          {d.entries.length === 0 && <tr><td colSpan={5} className="py-4 text-center text-muted-foreground">Nothing in the ledger for {year}.</td></tr>}
          {d.entries.map((x) => <tr key={x.id}><td className="py-1.5">{x.date}</td><td className="capitalize">{x.leave_type}</td><td>{KIND_LABEL[x.kind] ?? x.kind}</td><td className="text-right tabular">{x.days > 0 ? '+' : ''}{x.days}</td><td className="pl-3 text-[12px] text-muted-foreground">{x.note}</td></tr>)}
        </tbody>
      </table>
      <section aria-label="Adjust leave" className="mt-5 grid gap-3 border-t border-border pt-4 sm:grid-cols-3">
        <Field label="Leave" htmlFor="lg-type"><Select id="lg-type" value={f.leave_type} onChange={(e) => setF((x) => ({ ...x, leave_type: e.target.value }))} options={[{ value: 'annual', label: 'Annual' }, { value: 'sick', label: 'Sick' }]} /></Field>
        <Field label="Days (negative to take away)" htmlFor="lg-days"><NumField id="lg-days" value={f.days} onValue={(n) => setF((x) => ({ ...x, days: n }))} /></Field>
        <Field label="Why" htmlFor="lg-note" className="sm:col-span-3"><Textarea id="lg-note" rows={2} value={f.note} onChange={(e) => setF((x) => ({ ...x, note: e.target.value }))} /></Field>
        <div className="flex justify-end sm:col-span-3"><Button loading={save.isPending} disabled={!f.days || f.note.trim().length < 3} onClick={() => save.mutate()}>Adjust</Button></div>
      </section>
    </div>
  )
}
