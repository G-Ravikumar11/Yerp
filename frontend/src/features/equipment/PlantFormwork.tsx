import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileSpreadsheet, Plus } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Card, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { plantKeys, useProviders } from '@/api/plant'
import { apiUrl, get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { LoadError, usePaged } from './plantParts'

interface HireReturn { id: number; returned_on: string; returned_qty: number; damaged_qty: number; lost_qty: number; billable_days: number; hire_charge: number; loss_charge: number; damage_charge: number; by: string }
interface HirePayment { id: number; paid_on: string; amount: number; reference: string }
interface Hire {
  id: number; number: string; job_id: number; project: string; kind: string; supplier: string; description: string; quantity: number; uom: string; start_date: string; expected_return: string; actual_return: string
  daily_rate: number; replacement_cost: number; remarks: string; out: number; returned: number; damaged: number; lost: number; hire_charged: number; accrued: number; total_hire: number; loss_charge: number; damage_charge: number
  payable: number; paid: number; balance: number; status: string; returns: HireReturn[]; payments: HirePayment[]
}
interface Report {
  projects: { job_id: number; project: string; shuttering_qty: number; scaffolding_qty: number; daily_rental: number; outstanding_qty: number; total_hire: number; loss_charge: number; damage_charge: number; total_cost: number }[]
  vendors: { supplier: string; total_hire: number; loss_charge: number; damage_charge: number; total_cost: number; paid: number }[]
  lost_damaged: { number: string; project: string; kind: string; description: string; lost: number; damaged: number; uom: string; replacement_cost: number; loss_charge: number; damage_charge: number }[]
}
interface Charges { hire_charge: number; loss_charge: number; damage_charge: number; billable_days: number; payable: number }

const TONE: Record<string, 'success' | 'warning' | 'danger' | 'info'> = { 'On hire': 'info', 'Partially returned': 'warning', 'Fully returned': 'success', Overdue: 'danger' }
const th = 'px-3 py-2 text-left text-xs font-medium text-muted-foreground'
const newKey = () => `${Date.now()}-${Math.random().toString(36).slice(2)}`

/** Shuttering and scaffolding hired for each project: what is out, what came back, and what it cost. */
export function FormworkHire() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [adding, setAdding] = useState(false)
  const [returning, setReturning] = useState<Hire | null>(null)
  const [paying, setPaying] = useState<Hire | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const q = useQuery({ queryKey: ['equipment', 'formwork', job, kind, status], queryFn: () => get<{ hires: Hire[]; counts: Record<string, number>; billing_rule: string }>(`/api/plant/formwork?job_id=${job ?? 0}&kind=${kind}&status=${encodeURIComponent(status)}`) })
  const manage = can('stores.manage|workorders.manage')
  const { shown, pager } = usePaged(q.data?.hires)
  const current = q.data?.hires.find((h) => h.id === open) ?? null
  const cols: TableColumn<Hire>[] = [
    { id: 'n', header: 'Hire', cell: (h) => <button type="button" className="text-left font-mono text-[13px] font-semibold text-primary hover:underline" onClick={() => setOpen(open === h.id ? null : h.id)}>{h.number}<div className="font-sans text-xs font-normal text-muted-foreground">{h.kind}</div></button> },
    { id: 'p', header: 'Project', cell: (h) => <div>{h.project}<div className="text-xs text-muted-foreground">{h.supplier}</div></div> },
    { id: 'd', header: 'Equipment', hideBelow: 'md', cell: (h) => h.description },
    { id: 'q', header: 'Out / hired', align: 'right', cell: (h) => <div>{h.out} / {h.quantity} {h.uom}{(h.lost > 0 || h.damaged > 0) && <div className="text-xs text-warning">{h.lost} lost, {h.damaged} damaged</div>}</div> },
    { id: 'dt', header: 'Dates', hideBelow: 'lg', cell: (h) => <div className="text-[13px]">{formatDate(h.start_date)}<div className="text-xs text-muted-foreground">Due {h.expected_return ? formatDate(h.expected_return) : '-'}</div></div> },
    { id: 'r', header: 'Rate', hideBelow: 'lg', align: 'right', cell: (h) => `${formatINR(h.daily_rate)}/day` },
    { id: 't', header: 'Payable', align: 'right', sort: (h) => h.payable, cell: (h) => <div>{formatINR(h.payable)}{h.accrued > 0 && <div className="text-xs text-muted-foreground">{formatINR(h.accrued)} still running</div>}</div> },
    { id: 's', header: 'Status', cell: (h) => <Badge tone={TONE[h.status] ?? 'info'} dot>{h.status}</Badge> },
    {
      id: 'a', header: '', align: 'right',
      cell: (h) => <div className="flex justify-end gap-1">{h.out > 0 && (manage || can('site.record')) && <Button size="sm" variant="outline" onClick={() => setReturning(h)}>Return</Button>}{can('stores.manage|workorders.manage|accounts.manage|bills.pay') && h.balance > 0 && <Button size="sm" variant="ghost" onClick={() => setPaying(h)}>Pay</Button>}</div>,
    },
  ]
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-full sm:w-72"><ProjectPicker id="fw-job" value={job} onChange={setJob} allowAll /></div>
        <div className="w-40"><Select aria-label="Equipment type" value={kind} placeholder="Both types" onChange={(e) => setKind(e.target.value)} options={['Shuttering', 'Scaffolding'].map((x) => ({ value: x, label: x }))} /></div>
        <div className="w-44"><Select aria-label="Hire status" value={status} placeholder="Any status" onChange={(e) => setStatus(e.target.value)} options={Object.keys(TONE).map((x) => ({ value: x, label: x }))} /></div>
        {manage && <Button className="ml-auto" onClick={() => setAdding(true)}><Plus /> Hire</Button>}
      </div>
      {q.data && <p className="mb-2 text-[13px] text-muted-foreground">{q.data.counts['On hire']} on hire - {q.data.counts['Partially returned']} partly returned - {q.data.counts.Overdue} overdue - {q.data.counts['Fully returned']} returned. Billed {q.data.billing_rule === 'inclusive' ? 'counting the day it goes back' : 'not counting the day it goes back'}.</p>}
      {q.isError ? <LoadError message={q.error.message} retry={() => q.refetch()} /> : <Card className="overflow-hidden"><DataTable label="Shuttering and scaffolding hires" className="rounded-none border-0 shadow-none" rows={shown} columns={cols} rowKey={(h) => h.id} loading={q.isPending} empty="No shuttering or scaffolding hired." />{!q.isPending && pager}</Card>}
      {current && <History h={current} />}
      <HireReport />
      {adding && <HireModal onClose={() => setAdding(false)} />}
      {returning && <ReturnModal hire={returning} onClose={() => setReturning(null)} />}
      {paying && <PayModal hire={paying} onClose={() => setPaying(null)} />}
    </div>
  )
}

function History({ h }: { h: Hire }) {
  return (
    <section aria-label={`${h.number} history`} className="mt-4 rounded-xl border border-border bg-card p-4">
      <h3 className="mb-2 text-sm font-semibold">{h.number} returns and payments</h3>
      <div className="overflow-x-auto"><table aria-label="Returns" className="w-full min-w-[40rem] text-[13px]">
        <thead className="bg-surface"><tr><th className={th}>Date</th><th className={th}>Back</th><th className={th}>Damaged</th><th className={th}>Lost</th><th className={th}>Days</th><th className={th}>Hire</th><th className={th}>Replacement</th><th className={th}>Damage</th></tr></thead>
        <tbody>{h.returns.length ? h.returns.map((r) => <tr key={r.id} className="border-t border-border"><td className="px-3 py-2">{formatDate(r.returned_on)}</td><td className="px-3 py-2">{r.returned_qty}</td><td className="px-3 py-2">{r.damaged_qty}</td><td className="px-3 py-2">{r.lost_qty}</td><td className="px-3 py-2">{r.billable_days}</td><td className="px-3 py-2">{formatINR(r.hire_charge)}</td><td className="px-3 py-2">{formatINR(r.loss_charge)}</td><td className="px-3 py-2">{formatINR(r.damage_charge)}</td></tr>) : <tr><td colSpan={8} className="px-3 py-3 text-center text-muted-foreground">Nothing returned yet.</td></tr>}</tbody>
      </table></div>
      <p className="mt-2 text-[13px]">Paid {formatINR(h.paid)} of {formatINR(h.payable)}{h.payments.length > 0 && `: ${h.payments.map((p) => `${formatDate(p.paid_on)} ${formatINR(p.amount)}${p.reference ? ` (${p.reference})` : ''}`).join(', ')}`}</p>
    </section>
  )
}

function HireReport() {
  const q = useQuery({ queryKey: ['equipment', 'formwork-report'], queryFn: () => get<Report>('/api/plant/formwork-report') })
  const d = q.data
  if (!d || !d.projects.length) return null
  return (
    <section aria-label="Hire reports" className="mt-5">
      <div className="mb-2 flex items-center justify-between"><h3 className="text-sm font-semibold">Hire by project</h3><Button size="sm" variant="outline" asChild><a href={apiUrl('/api/plant/formwork-report.xlsx')}><FileSpreadsheet /> Download</a></Button></div>
      <div className="mb-4 overflow-x-auto rounded-lg border border-border"><table aria-label="Hire by project" className="w-full min-w-[44rem] text-[13px]">
        <thead className="bg-surface"><tr><th className={th}>Project</th><th className={th}>Shuttering</th><th className={th}>Scaffolding</th><th className={th}>Outstanding</th><th className={th}>Daily rent now</th><th className={th}>Hire</th><th className={th}>Replacement</th><th className={th}>Damage</th><th className={th}>Total</th></tr></thead>
        <tbody>{d.projects.map((p) => <tr key={p.job_id} className="border-t border-border"><td className="px-3 py-2">{p.project}</td><td className="px-3 py-2">{p.shuttering_qty}</td><td className="px-3 py-2">{p.scaffolding_qty}</td><td className="px-3 py-2">{p.outstanding_qty}</td><td className="px-3 py-2">{formatINR(p.daily_rental)}</td><td className="px-3 py-2">{formatINR(p.total_hire)}</td><td className="px-3 py-2">{formatINR(p.loss_charge)}</td><td className="px-3 py-2">{formatINR(p.damage_charge)}</td><td className="px-3 py-2 font-semibold">{formatINR(p.total_cost)}</td></tr>)}</tbody>
      </table></div>
      <h3 className="mb-2 text-sm font-semibold">Hire by vendor</h3>
      <div className="mb-4 overflow-x-auto rounded-lg border border-border"><table aria-label="Hire by vendor" className="w-full min-w-[32rem] text-[13px]">
        <thead className="bg-surface"><tr><th className={th}>Vendor</th><th className={th}>Hire</th><th className={th}>Replacement</th><th className={th}>Damage</th><th className={th}>Total</th><th className={th}>Paid</th></tr></thead>
        <tbody>{d.vendors.map((v) => <tr key={v.supplier} className="border-t border-border"><td className="px-3 py-2">{v.supplier}</td><td className="px-3 py-2">{formatINR(v.total_hire)}</td><td className="px-3 py-2">{formatINR(v.loss_charge)}</td><td className="px-3 py-2">{formatINR(v.damage_charge)}</td><td className="px-3 py-2 font-semibold">{formatINR(v.total_cost)}</td><td className="px-3 py-2">{formatINR(v.paid)}</td></tr>)}</tbody>
      </table></div>
      {d.lost_damaged.length > 0 && <>
        <h3 className="mb-2 text-sm font-semibold">Lost and damaged</h3>
        <ul aria-label="Lost and damaged" className="grid gap-1 text-[13px]">{d.lost_damaged.map((l) => <li key={l.number}><strong>{l.number}</strong> {l.project}: {l.lost} lost, {l.damaged} damaged {l.uom} of {l.description} - replacement {formatINR(l.loss_charge)}, damage {formatINR(l.damage_charge)}</li>)}</ul>
      </>}
    </section>
  )
}

function HireModal({ onClose }: { onClose: () => void }) {
  const prov = useProviders()
  const [job, setJob] = useState(0)
  const [f, setF] = useState({ kind: 'Shuttering', provider_id: 0, description: '', uom: 'Sqm', start_date: today(), expected_return: '', remarks: '' })
  const [n, setN] = useState({ quantity: 0, daily_rate: 0, replacement_cost: 0 })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const save = useAction(() => post<{ message: string }>('/api/plant/formwork', { ...f, ...n, provider_id: Number(f.provider_id), job_id: job }), { invalidate: [plantKeys.all], success: (r) => r.message, onSuccess: onClose })
  const ready = job && f.provider_id && f.description.trim() && n.quantity > 0 && n.daily_rate > 0 && f.start_date
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title="Hire shuttering or scaffolding" footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!ready || save.isPending} onClick={() => save.mutate()}>Save the hire</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Project" htmlFor="fh-job"><ProjectPicker id="fh-job" value={job} onChange={setJob} /></Field>
        <Field label="Equipment type" htmlFor="fh-kind"><Select id="fh-kind" value={f.kind} onChange={set('kind')} options={['Shuttering', 'Scaffolding'].map((x) => ({ value: x, label: x }))} /></Field>
        <Field label="Supplier" htmlFor="fh-sup" hint="From the rental providers"><Select id="fh-sup" value={f.provider_id || ''} placeholder="Choose the supplier" onChange={set('provider_id')} options={(prov.data?.providers ?? []).map((p) => ({ value: p.id, label: p.name }))} /></Field>
        <Field label="Equipment description" htmlFor="fh-desc"><Input id="fh-desc" value={f.description} maxLength={300} onChange={set('description')} /></Field>
        <Field label="Quantity" htmlFor="fh-qty"><NumField id="fh-qty" value={n.quantity} onValue={(v) => setN((x) => ({ ...x, quantity: v }))} /></Field>
        <Field label="Unit" htmlFor="fh-uom"><Input id="fh-uom" value={f.uom} maxLength={20} onChange={set('uom')} /></Field>
        <Field label="Hire start" htmlFor="fh-start"><Input id="fh-start" type="date" value={f.start_date} onChange={set('start_date')} /></Field>
        <Field label="Expected return" htmlFor="fh-ret"><Input id="fh-ret" type="date" min={f.start_date} value={f.expected_return} onChange={set('expected_return')} /></Field>
        <Field label="Daily hire rate" htmlFor="fh-rate"><NumField id="fh-rate" value={n.daily_rate} onValue={(v) => setN((x) => ({ ...x, daily_rate: v }))} /></Field>
        <Field label="Replacement cost per unit" htmlFor="fh-repl" hint="Charged for what is lost, once"><NumField id="fh-repl" value={n.replacement_cost} onValue={(v) => setN((x) => ({ ...x, replacement_cost: v }))} /></Field>
        <Field label="Remarks" htmlFor="fh-rem" className="sm:col-span-2"><Input id="fh-rem" value={f.remarks} onChange={set('remarks')} /></Field>
      </div>
      {save.error && <p role="alert" className="mt-3 text-[13px] text-danger">{save.error.message}</p>}
    </Modal>
  )
}

function ReturnModal({ hire: h, onClose }: { hire: Hire; onClose: () => void }) {
  const key = useMemo(newKey, [])
  const [on, setOn] = useState(today())
  const [n, setN] = useState({ returned_qty: 0, damaged_qty: 0, lost_qty: 0, damage_charge: 0 })
  const [charges, setCharges] = useState<Charges | null>(null)
  const body = { return_key: key, returned_on: on, ...n }
  const check = useAction(() => post<Charges>(`/api/plant/formwork/${h.id}/returns`, { ...body, preview: true }), { success: false, onSuccess: (r) => setCharges(r) })
  const save = useAction(() => post<{ message: string }>(`/api/plant/formwork/${h.id}/returns`, body), { invalidate: [plantKeys.all], success: (r) => r.message, onSuccess: onClose })
  const num = (k: keyof typeof n) => (v: number) => { setCharges(null); setN((x) => ({ ...x, [k]: v })) }
  const total = n.returned_qty + n.damaged_qty + n.lost_qty
  const over = total > h.out
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Return ${h.number}`} description={`${h.out} ${h.uom} still out of ${h.quantity}. ${h.description}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>{charges ? <Button loading={save.isPending} disabled={save.isPending} onClick={() => save.mutate()}>Confirm the return</Button> : <Button loading={check.isPending} disabled={!total || over || check.isPending} onClick={() => check.mutate()}>Work out the charges</Button>}</>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Return date" htmlFor="fr-on"><Input id="fr-on" type="date" min={h.start_date} max={today()} value={on} onChange={(e) => { setCharges(null); setOn(e.target.value) }} /></Field>
        <Field label={`Returned in good order (${h.uom})`} htmlFor="fr-back" error={over ? `Only ${h.out} ${h.uom} is out.` : undefined}><NumField id="fr-back" value={n.returned_qty} onValue={num('returned_qty')} /></Field>
        <Field label={`Damaged (${h.uom})`} htmlFor="fr-dam"><NumField id="fr-dam" value={n.damaged_qty} onValue={num('damaged_qty')} /></Field>
        <Field label={`Lost (${h.uom})`} htmlFor="fr-lost" hint={`At ${formatINR(h.replacement_cost)} each`}><NumField id="fr-lost" value={n.lost_qty} onValue={num('lost_qty')} /></Field>
        <Field label="Damage charge" htmlFor="fr-dch" className="sm:col-span-2"><NumField id="fr-dch" value={n.damage_charge} onValue={num('damage_charge')} /></Field>
      </div>
      {charges && (
        <dl aria-label="Charges" className="mt-4 grid grid-cols-2 gap-y-1 rounded-lg border border-border bg-surface p-3 text-[13px]">
          <dt>Hire, {charges.billable_days} days</dt><dd className="text-right tabular">{formatINR(charges.hire_charge)}</dd>
          <dt>Replacement for what is lost</dt><dd className="text-right tabular">{formatINR(charges.loss_charge)}</dd>
          <dt>Damage</dt><dd className="text-right tabular">{formatINR(charges.damage_charge)}</dd>
          <dt className="font-semibold">Payable for this return</dt><dd className="text-right font-semibold tabular">{formatINR(charges.payable)}</dd>
        </dl>
      )}
      {(check.error || save.error) && <p role="alert" className="mt-3 text-[13px] text-danger">{(check.error ?? save.error)?.message}</p>}
    </Modal>
  )
}

function PayModal({ hire: h, onClose }: { hire: Hire; onClose: () => void }) {
  const [amount, setAmount] = useState(0)
  const [ref, setRef] = useState('')
  const [on, setOn] = useState(today())
  const save = useAction(() => post<{ message: string }>(`/api/plant/formwork/${h.id}/payments`, { amount, paid_on: on, reference: ref }), { invalidate: [plantKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Pay ${h.number}`} description={`${formatINR(h.balance)} outstanding, including hire still running.`} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!(amount > 0) || save.isPending} onClick={() => save.mutate()}>Record the payment</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Amount" htmlFor="fp-amt"><NumField id="fp-amt" value={amount} onValue={setAmount} /></Field>
        <Field label="Paid on" htmlFor="fp-on"><Input id="fp-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Reference" htmlFor="fp-ref" className="sm:col-span-2"><Input id="fp-ref" value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
      </div>
    </Modal>
  )
}
