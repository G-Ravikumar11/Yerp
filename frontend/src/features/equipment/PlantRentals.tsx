import { useState } from 'react'
import { Paperclip, Plus, Trash2, Users } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilesModal } from '@/components/data/FilesModal'
import { Badge, Button, Card, ConfirmDialog, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import {
  addRentalInvoice, createRental, decideExpense, extendRental, payRentalInvoice, plantKeys, removeExpense, returnRental, saveExpense, saveProvider,
  useExpenses, useProviders, useRentals, type Expense, type Provider, type Rental, type RentalInvoice,
} from '@/api/plant'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { FormFoot, LoadError, MachineSelect, RangeBar, usePaged } from './plantParts'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

const rentTone = (s: string) => (s === 'Overdue' ? 'danger' : s === 'Returned' ? 'neutral' : s === 'Upcoming' ? 'info' : s === 'Extended' ? 'warning' : 'success') as 'danger' | 'neutral' | 'info' | 'warning' | 'success'

// ---- rentals ---------------------------------------------------------------------------------------

export function Rentals() {
  const { can } = useSession()
  const manage = can('stores.manage|workorders.manage')
  const [status, setStatus] = useState('')
  const [provider, setProvider] = useState(0)
  const q = useRentals({ status, provider_id: provider })
  const prov = useProviders()
  const [adding, setAdding] = useState(false)
  const [providers, setProviders] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const current = q.data?.rentals.find((r) => r.id === open) ?? null
  const { shown, pager } = usePaged(q.data?.rentals)
  const s = q.data?.summary
  const cols: TableColumn<Rental>[] = [
    { id: 'n', header: 'Rental', cell: (r) => <button type="button" className="text-left font-mono text-[13px] font-semibold text-primary hover:underline" onClick={() => setOpen(r.id)}>{r.number}<div className="font-sans text-xs font-normal text-muted-foreground">{r.agreement_no}</div></button> },
    { id: 'm', header: 'Machine', cell: (r) => <div><span className="font-mono text-[13px]">{r.code}</span> {r.machine}<div className="text-xs text-muted-foreground">{[r.category, r.reg_no].filter(Boolean).join(' - ')}</div></div> },
    { id: 'p', header: 'Provider', hideBelow: 'md', cell: (r) => <div>{r.provider?.name}<div className="text-xs text-muted-foreground">{r.provider?.mobile}</div></div> },
    { id: 'd', header: 'Dates', hideBelow: 'md', sort: (r) => r.expected_return, cell: (r) => <div className="text-[13px]">{formatDate(r.start_date)} - {formatDate(r.actual_return || r.expected_return)}{r.days_left != null && <div className={r.days_left < 0 ? 'font-semibold text-danger' : 'text-muted-foreground'}>{r.days_left < 0 ? `${-r.days_left} days overdue` : `${r.days_left} days left`}</div>}</div> },
    { id: 'rate', header: 'Rate', hideBelow: 'lg', align: 'right', cell: (r) => <div>{formatINR(r.rate)}<div className="text-xs text-muted-foreground">{r.billing}</div></div> },
    { id: 'h', header: 'Used / billed h', hideBelow: 'lg', align: 'right', cell: (r) => <div>{r.used_hours} / {r.billed_hours}{r.hours_gap !== 0 && <div className={`text-xs ${r.hours_gap > 0 ? 'text-warning' : 'text-muted-foreground'}`}>{r.hours_gap > 0 ? `billed ${r.hours_gap} h more` : `${-r.hours_gap} h not yet billed`}</div>}</div> },
    { id: 'o', header: 'Outstanding', align: 'right', sort: (r) => r.outstanding, cell: (r) => <span className={r.outstanding ? 'font-semibold' : ''}>{formatINR(r.outstanding)}</span> },
    { id: 's', header: 'Status', cell: (r) => <Badge tone={rentTone(r.status)} dot>{r.status}</Badge> },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="rental" id={r.id} label={r.number} noun="rental" /> },
  ]
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-40"><Select aria-label="Status" value={status} placeholder="Any status" onChange={(e) => setStatus(e.target.value)} options={['Upcoming', 'Active', 'Extended', 'Overdue', 'Returned'].map((x) => ({ value: x, label: x }))} /></div>
        <div className="w-52"><Select aria-label="Provider" value={provider || ''} placeholder="Every provider" onChange={(e) => setProvider(Number(e.target.value) || 0)} options={(prov.data?.providers ?? []).map((p) => ({ value: p.id, label: p.name }))} /></div>
        {s && <span className="text-[13px] text-muted-foreground">{s.Active + s.Extended} on hire - {s.Overdue} overdue - <strong className="text-foreground">{formatINR(s.outstanding)}</strong> owed</span>}
        <span className="ml-auto flex gap-2">
          {manage && <Button variant="outline" onClick={() => setProviders(true)}><Users /> Providers</Button>}
          {manage && <Button onClick={() => setAdding(true)}><Plus /> Hire agreement</Button>}
        </span>
      </div>
      {q.isError ? <LoadError message={q.error.message} retry={() => q.refetch()} /> : (
        <Card className="overflow-hidden"><DataTable label="Rentals" className="rounded-none border-0 shadow-none" rows={shown} columns={cols} rowKey={(r) => r.id} loading={q.isPending} empty="No machines hired in. Add the provider, mark the machine Rented on the register, then record the agreement." />{!q.isPending && pager}</Card>
      )}
      <RentalModal open={adding} providers={prov.data?.providers ?? []} billing={q.data?.billing ?? ['Daily']} onClose={() => setAdding(false)} />
      <ProvidersModal open={providers} onClose={() => setProviders(false)} />
      <RentalDetail rental={current} manage={manage} onClose={() => setOpen(null)} />
    </div>
  )
}

function RentalModal({ open, providers, billing, onClose }: { open: boolean; providers: Provider[]; billing: string[]; onClose: () => void }) {
  return <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Record a hire agreement" description="Its own rate and billing - not every hire is billed the same way." size="lg">{open && <RentalForm providers={providers} billing={billing} onClose={onClose} />}</Modal>
}

function RentalForm({ providers, billing, onClose }: { providers: Provider[]; billing: string[]; onClose: () => void }) {
  const [f, setF] = useState({ asset_id: 0, provider_id: 0, agreement_no: '', start_date: today(), expected_return: '', billing: 'Daily', notes: '' })
  const [n, setN] = useState({ rate: 0, min_billable_hours: 0, overtime_rate: 0, transport_charges: 0, deposit: 0, advance: 0 })
  const [inc, setInc] = useState({ fuel_included: false, operator_included: false })
  const [tried, setTried] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const num = (k: keyof typeof n) => (v: number) => setN((x) => ({ ...x, [k]: v }))
  const errors = { asset: f.asset_id ? '' : 'Choose a rented machine.', prov: f.provider_id ? '' : 'Choose the provider.', ag: f.agreement_no.trim() ? '' : 'The agreement number.', ret: !f.expected_return ? 'The expected return date.' : f.expected_return < f.start_date ? 'Not before the start.' : '', rate: n.rate > 0 ? '' : 'The rental rate.' }
  const bad = Object.values(errors).some(Boolean)
  const save = useAction(() => createRental({ ...f, ...n, ...inc }), { invalidate: [plantKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Machine" htmlFor="rn-m" error={tried ? errors.asset : ''} hint="Machines marked Rented or Leased on the register" className="sm:col-span-2"><MachineSelect id="rn-m" value={f.asset_id} onChange={(v) => setF((x) => ({ ...x, asset_id: v }))} filter={(m) => m.ownership !== 'Owned'} emptyText="No rented machines - mark one Rented on the register" /></Field>
        <Field label="Provider" htmlFor="rn-p" error={tried ? errors.prov : ''}><Select id="rn-p" value={f.provider_id || ''} placeholder={providers.length ? 'Choose' : 'Add one under Providers'} onChange={(e) => setF((x) => ({ ...x, provider_id: Number(e.target.value) || 0 }))} options={providers.map((p) => ({ value: p.id, label: p.name }))} /></Field>
        <Field label="Agreement no." htmlFor="rn-a" error={tried ? errors.ag : ''}><Input id="rn-a" value={f.agreement_no} onChange={set('agreement_no')} /></Field>
        <Field label="Start" htmlFor="rn-s"><Input id="rn-s" type="date" value={f.start_date} onChange={set('start_date')} /></Field>
        <Field label="Expected return" htmlFor="rn-r" error={tried ? errors.ret : ''}><Input id="rn-r" type="date" min={f.start_date} value={f.expected_return} onChange={set('expected_return')} /></Field>
        <Field label="Rate" htmlFor="rn-rate" error={tried ? errors.rate : ''}><NumField id="rn-rate" value={n.rate} onValue={num('rate')} /></Field>
        <Field label="Billed" htmlFor="rn-b"><Select id="rn-b" value={f.billing} onChange={set('billing')} options={billing.map((b) => ({ value: b, label: b }))} /></Field>
        <Field label="Minimum billable hours" htmlFor="rn-min"><NumField id="rn-min" value={n.min_billable_hours} onValue={num('min_billable_hours')} /></Field>
        <Field label="Overtime rate" htmlFor="rn-ot"><NumField id="rn-ot" value={n.overtime_rate} onValue={num('overtime_rate')} /></Field>
        <Field label="Transport charges" htmlFor="rn-t"><NumField id="rn-t" value={n.transport_charges} onValue={num('transport_charges')} /></Field>
        <Field label="Deposit" htmlFor="rn-d"><NumField id="rn-d" value={n.deposit} onValue={num('deposit')} /></Field>
        <Field label="Advance paid" htmlFor="rn-adv"><NumField id="rn-adv" value={n.advance} onValue={num('advance')} /></Field>
        <div className="flex flex-col justify-end gap-1.5 text-sm"><label className="flex items-center gap-2"><input type="checkbox" checked={inc.fuel_included} onChange={(e) => setInc((x) => ({ ...x, fuel_included: e.target.checked }))} /> Fuel included</label><label className="flex items-center gap-2"><input type="checkbox" checked={inc.operator_included} onChange={(e) => setInc((x) => ({ ...x, operator_included: e.target.checked }))} /> Operator included</label></div>
        <Field label="Terms and notes" htmlFor="rn-n" className="sm:col-span-3"><Textarea id="rn-n" rows={2} value={f.notes} onChange={set('notes')} /></Field>
      </div>
      <FormFoot error={save.error?.message} busy={save.isPending} label="Record the agreement" onClose={onClose} onSave={() => (bad ? setTried(true) : save.mutate())} />
    </div>
  )
}

function RentalDetail({ rental: r, manage, onClose }: { rental: Rental | null; manage: boolean; onClose: () => void }) {
  const [extending, setExtending] = useState(false)
  const [returning, setReturning] = useState(false)
  const [billing, setBilling] = useState(false)
  const [paying, setPaying] = useState<RentalInvoice | null>(null)
  const [files, setFiles] = useState(false)
  const back = useAction((on: string) => returnRental(r!.id, on), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: () => setReturning(false) })
  const live = r && !r.actual_return
  return (
    <Modal open={!!r} onOpenChange={(o) => !o && onClose()} title={r ? `${r.number} - ${r.code} ${r.machine}` : ''} description={r ? `${r.provider?.name ?? ''}, agreement ${r.agreement_no}` : ''} size="xl">
      {r && (
        <div className="grid gap-4">
          <div className="flex flex-wrap items-center gap-2"><Badge tone={rentTone(r.status)} dot>{r.status}</Badge>{r.fuel_included && <Badge>Fuel included</Badge>}{r.operator_included && <Badge>Operator included</Badge>}</div>
          <dl className="grid grid-cols-2 gap-3 text-[13px] sm:grid-cols-4">
            {([['Start', formatDate(r.start_date)], ['Return due', formatDate(r.expected_return)], ['Returned', r.actual_return ? formatDate(r.actual_return) : '-'], ['Rate', `${formatINR(r.rate)} ${r.billing.toLowerCase()}`],
              ['Minimum billable', r.min_billable_hours ? `${r.min_billable_hours} h` : '-'], ['Overtime rate', r.overtime_rate ? formatINR(r.overtime_rate) : '-'], ['Transport', formatINR(r.transport_charges)], ['Deposit / advance', `${formatINR(r.deposit)} / ${formatINR(r.advance)}`],
              ['Provider contact', `${r.provider?.contact_person ?? ''} ${r.provider?.mobile ?? ''}`], ['Hours used', `${r.used_hours} h`], ['Hours billed', `${r.billed_hours} h`], ['Outstanding', formatINR(r.outstanding)]] as [string, string][]).map(([k, v]) => <div key={k}><dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{k}</dt><dd>{v}</dd></div>)}
          </dl>
          {r.notes && <p className="text-[13px] text-muted-foreground">{r.notes}</p>}
          <section><h3 className="mb-2 text-sm font-semibold">Invoices</h3>
            {r.invoices.length === 0 ? <p className="text-[13px] text-muted-foreground">No invoice yet.</p> : (
              <div className="overflow-x-auto rounded-lg border border-border"><table aria-label="Rental invoices" className="w-full text-[13px]"><thead className="bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Invoice</th><th className="px-3">Period</th><th className="px-3 text-right">Hours</th><th className="px-3 text-right">Amount</th><th className="px-3 text-right">Paid</th><th className="px-3 text-right">Outstanding</th><th /></tr></thead>
                <tbody>{r.invoices.map((i) => <tr key={i.id} className="border-t border-border"><td className="px-3 py-2">{i.invoice_no}<div className="text-xs text-muted-foreground">{formatDate(i.invoice_date)}</div></td><td className="px-3">{i.period_from && `${formatDate(i.period_from)} - ${formatDate(i.period_to)}`}</td><td className="px-3 text-right tabular">{i.billed_hours}</td><td className="px-3 text-right tabular">{formatINR(i.amount)}</td><td className="px-3 text-right tabular">{formatINR(i.paid)}{i.paid_on && <div className="text-xs text-muted-foreground">{formatDate(i.paid_on)} {i.payment_ref}</div>}</td><td className="px-3 text-right tabular font-semibold">{formatINR(i.outstanding)}</td><td className="px-3 text-right">{manage && i.outstanding > 0 && <Button size="sm" variant="outline" onClick={() => setPaying(i)}>Pay</Button>}</td></tr>)}</tbody></table></div>
            )}
          </section>
          <section><h3 className="mb-2 text-sm font-semibold">Agreement history</h3>
            <ul className="grid gap-1 text-[13px]"><li>Agreed from {formatDate(r.start_date)} to {formatDate(r.extensions[0]?.from ?? r.expected_return)}</li>{r.extensions.map((x, i) => <li key={i}>Extended {formatDate(x.from)} to <strong>{formatDate(x.to)}</strong>{x.reason && ` - ${x.reason}`} <span className="text-muted-foreground">({x.by})</span></li>)}{r.actual_return && <li>Returned {formatDate(r.actual_return)}</li>}</ul>
          </section>
          <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
            <Button variant="outline" onClick={() => setFiles(true)}><Paperclip /> Agreement and documents</Button>
            {manage && <Button variant="outline" onClick={() => setBilling(true)}>Add invoice</Button>}
            {manage && live && <Button variant="outline" onClick={() => setExtending(true)}>Extend</Button>}
            {manage && live && <Button onClick={() => setReturning(true)}>Return the machine</Button>}
          </div>
          <ExtendModal open={extending} rental={r} onClose={() => setExtending(false)} />
          <InvoiceModal open={billing} rental={r} onClose={() => setBilling(false)} />
          <PayModal invoice={paying} onClose={() => setPaying(null)} />
          <ReturnModal open={returning} rental={r} busy={back.isPending} error={back.error?.message} onClose={() => setReturning(false)} onReturn={(on) => back.mutate(on)} />
          {files && <FilesModal type="plant_rental" id={r.id} title={`${r.number} agreement and documents`} onClose={() => setFiles(false)} />}
        </div>
      )}
    </Modal>
  )
}

function ReturnModal({ open, rental: r, busy, error, onClose, onReturn }: { open: boolean; rental: Rental; busy: boolean; error?: string; onClose: () => void; onReturn: (on: string) => void }) {
  const [on, setOn] = useState(today())
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={`Return ${r.code} to ${r.provider?.name ?? 'its owner'}?`} description="It comes off its site, anyone allocated to it is taken off, and it can no longer be allocated.">
      {open && <>
        <Field label="Returned on" htmlFor="rt-on" error={on < r.start_date ? 'Not before it arrived.' : on > today() ? 'Not in the future.' : ''}><Input id="rt-on" type="date" min={r.start_date} max={today()} value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
          {error && <p role="alert" className="mr-auto text-[13px] text-danger">{error}</p>}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button loading={busy} disabled={on < r.start_date || on > today()} onClick={() => onReturn(on)}>Yes</Button>
        </div>
      </>}
    </Modal>
  )
}

function ExtendModal({ open, rental: r, onClose }: { open: boolean; rental: Rental; onClose: () => void }) {
  const [to, setTo] = useState('')
  const [why, setWhy] = useState('')
  const save = useAction(() => extendRental(r.id, to, why), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: onClose })
  return <Modal open={open} onOpenChange={(o) => !o && onClose()} title={`Extend ${r.number}`} description={`Due back ${formatDate(r.expected_return)}.`}>{open && <><div className="grid gap-4"><Field label="New return date" htmlFor="ex-to" error={to && to <= r.expected_return ? 'After the present return date.' : ''}><Input id="ex-to" type="date" min={r.expected_return} value={to} onChange={(e) => setTo(e.target.value)} /></Field><Field label="Reason" htmlFor="ex-w"><Input id="ex-w" value={why} onChange={(e) => setWhy(e.target.value)} /></Field></div><FormFoot error={save.error?.message} busy={save.isPending} label="Extend" onClose={onClose} onSave={() => to > r.expected_return && save.mutate()} /></>}</Modal>
}

function InvoiceModal({ open, rental: r, onClose }: { open: boolean; rental: Rental; onClose: () => void }) {
  const [f, setF] = useState({ invoice_no: '', invoice_date: today(), period_from: '', period_to: '', paid_on: '', payment_ref: '' })
  const [n, setN] = useState({ billed_hours: 0, amount: 0, paid: 0 })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const ok = f.invoice_no.trim() && n.amount > 0 && n.paid >= 0 && n.paid <= n.amount
  const save = useAction(() => addRentalInvoice(r.id, { ...f, ...n }), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: onClose })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={`Invoice for ${r.number}`} description={`Used ${r.used_hours} h so far, ${r.billed_hours} h billed.`} size="lg">
      {open && <><div className="grid gap-4 sm:grid-cols-3">
        <Field label="Invoice no." htmlFor="ri-n"><Input id="ri-n" value={f.invoice_no} onChange={set('invoice_no')} /></Field>
        <Field label="Date" htmlFor="ri-d"><Input id="ri-d" type="date" value={f.invoice_date} onChange={set('invoice_date')} /></Field>
        <Field label="Hours billed" htmlFor="ri-h"><NumField id="ri-h" value={n.billed_hours} onValue={(v) => setN((x) => ({ ...x, billed_hours: v }))} /></Field>
        <Field label="Period from" htmlFor="ri-f"><Input id="ri-f" type="date" value={f.period_from} onChange={set('period_from')} /></Field>
        <Field label="Period to" htmlFor="ri-t"><Input id="ri-t" type="date" min={f.period_from} value={f.period_to} onChange={set('period_to')} /></Field>
        <Field label="Amount billed" htmlFor="ri-a"><NumField id="ri-a" value={n.amount} onValue={(v) => setN((x) => ({ ...x, amount: v }))} /></Field>
        <Field label="Paid now" htmlFor="ri-p" error={n.paid > n.amount ? 'More than the bill.' : ''}><NumField id="ri-p" value={n.paid} onValue={(v) => setN((x) => ({ ...x, paid: v }))} /></Field>
        <Field label="Paid on" htmlFor="ri-po"><Input id="ri-po" type="date" value={f.paid_on} onChange={set('paid_on')} /></Field>
        <Field label="Payment reference" htmlFor="ri-r"><Input id="ri-r" value={f.payment_ref} onChange={set('payment_ref')} /></Field>
      </div><FormFoot error={save.error?.message} busy={save.isPending} label="Record the invoice" onClose={onClose} onSave={() => ok && save.mutate()} /></>}
    </Modal>
  )
}

function PayModal({ invoice: i, onClose }: { invoice: RentalInvoice | null; onClose: () => void }) {
  const [amount, setAmount] = useState(0)
  const [on, setOn] = useState(today())
  const [ref, setRef] = useState('')
  const save = useAction(() => payRentalInvoice(i!.id, amount, on, ref), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: onClose })
  return <Modal open={!!i} onOpenChange={(o) => !o && onClose()} title={i ? `Pay ${i.invoice_no}` : ''} description={i ? `${formatINR(i.outstanding)} outstanding.` : ''}>{i && <><div className="grid gap-4 sm:grid-cols-3"><Field label="Amount" htmlFor="py-a" error={amount > i.outstanding ? 'More than is owed.' : ''}><NumField id="py-a" value={amount} onValue={setAmount} /></Field><Field label="Paid on" htmlFor="py-d"><Input id="py-d" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field><Field label="Reference" htmlFor="py-r"><Input id="py-r" value={ref} onChange={(e) => setRef(e.target.value)} /></Field></div><FormFoot error={save.error?.message} busy={save.isPending} label="Record payment" onClose={onClose} onSave={() => amount > 0 && amount <= i.outstanding && save.mutate()} /></>}</Modal>
}

function ProvidersModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const q = useProviders()
  const [edit, setEdit] = useState<Provider | 'new' | null>(null)
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Rental providers" description="Whoever machines are hired from." size="lg">
      {open && (edit ? <ProviderForm p={edit === 'new' ? null : edit} suppliers={q.data?.suppliers ?? []} onDone={() => setEdit(null)} /> : (
        <div>
          <div className="mb-3 flex justify-end"><Button size="sm" onClick={() => setEdit('new')}><Plus /> Provider</Button></div>
          {(q.data?.providers ?? []).length === 0 ? <p className="text-[13px] text-muted-foreground">None yet.</p> : <ul className="grid gap-2">{q.data!.providers.map((p) => <li key={p.id} className="flex items-center gap-3 rounded-lg border border-border p-3 text-[13px]"><div className="min-w-0 flex-1"><p className="font-medium">{p.name}</p><p className="text-xs text-muted-foreground">{[p.contact_person, p.mobile, p.email].filter(Boolean).join(' - ')}</p></div><Button size="sm" variant="outline" onClick={() => setEdit(p)}>Edit</Button><MasterDelete kind="rental_provider" id={p.id} label={p.name} noun="rental provider" /></li>)}</ul>}
        </div>
      ))}
    </Modal>
  )
}

function ProviderForm({ p, suppliers, onDone }: { p: Provider | null; suppliers: { id: number; name: string }[]; onDone: () => void }) {
  const [f, setF] = useState({ name: p?.name ?? '', contact_person: p?.contact_person ?? '', mobile: p?.mobile ?? '', email: p?.email ?? '', address: p?.address ?? '' })
  const [sup, setSup] = useState(p?.supplier_id ?? 0)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const save = useAction(() => saveProvider(p?.id ?? null, { ...f, supplier_id: sup || null }), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: onDone })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Company name" htmlFor="pv-n" error={f.name.trim() ? '' : 'Required.'}><Input id="pv-n" value={f.name} onChange={set('name')} /></Field>
        <Field label="Contact person" htmlFor="pv-c"><Input id="pv-c" value={f.contact_person} onChange={set('contact_person')} /></Field>
        <Field label="Mobile" htmlFor="pv-m"><Input id="pv-m" inputMode="tel" value={f.mobile} onChange={set('mobile')} /></Field>
        <Field label="Email" htmlFor="pv-e"><Input id="pv-e" type="email" value={f.email} onChange={set('email')} /></Field>
        <Field label="Address" htmlFor="pv-a" className="sm:col-span-2"><Textarea id="pv-a" rows={2} value={f.address} onChange={set('address')} /></Field>
        <Field label="Supplier in the ERP" htmlFor="pv-s" hint="Link to the supplier list, if they are on it"><Select id="pv-s" value={sup || ''} placeholder="Not linked" onChange={(e) => setSup(Number(e.target.value) || 0)} options={suppliers.map((s) => ({ value: s.id, label: s.name }))} /></Field>
      </div>
      <FormFoot error={save.error?.message} busy={save.isPending} label="Save" onClose={onDone} onSave={() => f.name.trim() && save.mutate()} />
    </div>
  )
}

// ---- expenses ----------------------------------------------------------------------------------------

const SOURCE: Record<string, string> = { expense: 'Entered here', fuel: 'Fuel register', maintenance: 'Maintenance', rental: 'Rental bill' }

export function Expenses() {
  const { can } = useSession()
  const manage = can('stores.manage|workorders.manage')
  const [r, setR] = useState({ from: '', to: '', asset: 0, category: '' })
  const q = useExpenses({ date_from: r.from, date_to: r.to, asset_id: r.asset, category: r.category })
  const [edit, setEdit] = useState<Expense | 'new' | null>(null)
  const [removing, setRemoving] = useState<Expense | null>(null)
  const [rejecting, setRejecting] = useState<Expense | null>(null)
  const [files, setFiles] = useState<Expense | null>(null)
  const decide = useAction((v: { e: Expense; d: 'approve' | 'reject'; remarks: string }) => decideExpense(v.e.id, v.d, v.remarks), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: () => setRejecting(null) })
  const del = useAction((e: Expense) => removeExpense(e.id), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: () => setRemoving(null) })
  const { shown, pager } = usePaged(q.data?.expenses)
  const cols: TableColumn<Expense>[] = [
    { id: 'n', header: 'ID', cell: (e) => <div><span className="font-mono text-[13px]">{e.number}</span><div className="text-xs text-muted-foreground">{SOURCE[e.source]}</div></div> },
    { id: 'd', header: 'Date', sort: (e) => e.spent_on, cell: (e) => formatDate(e.spent_on) },
    { id: 'm', header: 'Machine', cell: (e) => <div><span className="font-mono text-[13px]">{e.code}</span> {e.machine}</div> },
    { id: 'c', header: 'Category', cell: (e) => <div>{e.category}<div className="max-w-56 truncate text-xs text-muted-foreground" title={e.description}>{e.description}</div></div> },
    { id: 'a', header: 'Amount', align: 'right', sort: (e) => e.amount, cell: (e) => <div>{formatINR(e.amount)}{e.quantity > 0 && e.unit_rate > 0 && <div className="text-xs text-muted-foreground">{e.quantity} x {e.unit_rate}</div>}</div> },
    { id: 'v', header: 'Vendor / invoice', hideBelow: 'md', cell: (e) => <div>{e.vendor || '-'}<div className="text-xs text-muted-foreground">{e.invoice_no}</div></div> },
    { id: 'p', header: 'Payment', hideBelow: 'lg', cell: (e) => e.payment_status || '-' },
    { id: 's', header: 'Approval', cell: (e) => <Badge tone={e.approval_status === 'Approved' ? 'success' : e.approval_status === 'Rejected' ? 'danger' : e.approval_status === 'Pending' ? 'warning' : 'neutral'} dot>{e.approval_status}</Badge> },
    {
      id: 'act', header: '', align: 'right',
      cell: (e) => e.source !== 'expense' ? null : (
        <div className="flex justify-end gap-1">
          {can('site.signoff') && e.approval_status === 'Pending' && <><Button size="sm" onClick={() => decide.mutate({ e, d: 'approve', remarks: '' })}>Approve</Button><Button size="sm" variant="ghost" className="text-danger" onClick={() => setRejecting(e)}>Reject</Button></>}
          {manage && e.approval_status !== 'Approved' && <Button size="sm" variant="outline" onClick={() => setEdit(e)}>Edit</Button>}
          <Button size="sm" variant="ghost" aria-label={`Attachments for ${e.number}`} onClick={() => setFiles(e)}><Paperclip /></Button>
          {manage && e.approval_status !== 'Approved' && <Button size="sm" variant="ghost" className="text-danger" aria-label={`Delete ${e.number}`} onClick={() => setRemoving(e)}><Trash2 /></Button>}
        </div>
      ),
    },
  ]
  const d = q.data
  return (
    <div>
      <RangeBar from={r.from} to={r.to} onChange={(from, to) => setR((x) => ({ ...x, from, to }))}>
        <div className="w-52"><MachineSelect id="ex-fm" value={r.asset} onChange={(asset) => setR((x) => ({ ...x, asset }))} placeholder="Every machine" /></div>
        <div className="w-52"><Select aria-label="Category" value={r.category} placeholder="Every category" onChange={(e) => setR((x) => ({ ...x, category: e.target.value }))} options={(d?.all_categories ?? []).map((c) => ({ value: c, label: c }))} /></div>
        {manage && <Button className="ml-auto" onClick={() => setEdit('new')}><Plus /> Expense</Button>}
      </RangeBar>
      {d && <div className="mb-3 flex flex-wrap gap-2 text-[13px]">{Object.entries(d.by_category).map(([k, v]) => <span key={k} className="rounded-full border border-border px-3 py-1">{k}: <strong>{formatINR(v)}</strong></span>)}<span className="rounded-full bg-primary-soft px-3 py-1 font-semibold">Total {formatINR(d.total)}</span></div>}
      {q.isError ? <LoadError message={q.error.message} retry={() => q.refetch()} /> : (
        <Card className="overflow-hidden"><DataTable label="Equipment expenses" className="rounded-none border-0 shadow-none" rows={shown} columns={cols} rowKey={(e) => `${e.source}-${e.id}`} loading={q.isPending} empty="No expenses for these filters." />{!q.isPending && pager}</Card>
      )}
      <p className="mt-2 text-[11px] text-muted-foreground">Fuel, maintenance and rental bills come from their own registers and are shown here once. Spares, wages, transport, insurance and other costs are entered here. A rejected expense is not counted.</p>
      <ExpenseModal edit={edit} categories={d?.categories ?? []} onClose={() => setEdit(null)} />
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={removing ? `Delete ${removing.number}?` : ''} description="Do you want to delete this? It cannot be undone." confirmLabel="Yes" cancelLabel="Cancel" tone="danger" loading={del.isPending} onConfirm={() => { if (removing) del.mutate(removing) }} />
      <ConfirmDialog open={!!rejecting} onOpenChange={(o) => !o && setRejecting(null)} title="Reject this expense?" reason={{ label: 'Why', required: true }} confirmLabel="Reject" cancelLabel="Cancel" tone="danger" loading={decide.isPending} onConfirm={(remarks) => { if (rejecting) decide.mutate({ e: rejecting, d: 'reject', remarks }) }} />
      {files && <FilesModal type="plant_expense" id={files.id} title={`${files.number} invoice and documents`} onClose={() => setFiles(null)} />}
    </div>
  )
}

function ExpenseModal({ edit, categories, onClose }: { edit: Expense | 'new' | null; categories: string[]; onClose: () => void }) {
  const e = edit && edit !== 'new' ? edit : null
  return <Modal open={!!edit} onOpenChange={(o) => !o && onClose()} title={e ? `Edit ${e.number}` : 'Record an equipment expense'} description="Entered once, against its invoice or voucher." size="lg">{edit && <ExpenseForm e={e} categories={categories} onClose={onClose} />}</Modal>
}

function ExpenseForm({ e, categories, onClose }: { e: Expense | null; categories: string[]; onClose: () => void }) {
  const [f, setF] = useState({ asset_id: e?.asset_id ?? 0, category: e?.category ?? categories[0] ?? 'Other', spent_on: e?.spent_on ?? today(), description: e?.description ?? '', vendor: e?.vendor ?? '', invoice_no: e?.invoice_no ?? '', payment_status: e?.payment_status ?? 'Unpaid', payment_ref: e?.payment_ref ?? '' })
  const [n, setN] = useState({ quantity: e?.quantity ?? 0, unit_rate: e?.unit_rate ?? 0, amount: e?.amount ?? 0 })
  const [tried, setTried] = useState(false)
  const set = (k: keyof typeof f) => (ev: { target: { value: string } }) => setF((x) => ({ ...x, [k]: ev.target.value }))
  const computed = n.quantity > 0 && n.unit_rate > 0 ? Math.round(n.quantity * n.unit_rate * 100) / 100 : n.amount
  const errors = { asset: f.asset_id ? '' : 'Choose the machine.', desc: f.description.trim() ? '' : 'Describe the expense.', amount: computed > 0 ? '' : 'The amount.', date: f.spent_on > today() ? 'Not in the future.' : '' }
  const bad = Object.values(errors).some(Boolean)
  const save = useAction(() => saveExpense(e?.id ?? null, { ...f, quantity: n.quantity, unit_rate: n.unit_rate, amount: computed }), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Machine" htmlFor="xe-m" error={tried ? errors.asset : ''} className="sm:col-span-2"><MachineSelect id="xe-m" value={f.asset_id} onChange={(v) => setF((x) => ({ ...x, asset_id: v }))} /></Field>
        <Field label="Category" htmlFor="xe-c"><Select id="xe-c" value={f.category} onChange={set('category')} options={categories.map((c) => ({ value: c, label: c }))} /></Field>
        <Field label="Date" htmlFor="xe-d" error={tried ? errors.date : ''}><Input id="xe-d" type="date" max={today()} value={f.spent_on} onChange={set('spent_on')} /></Field>
        <Field label="Description" htmlFor="xe-ds" error={tried ? errors.desc : ''} className="sm:col-span-2"><Input id="xe-ds" value={f.description} onChange={set('description')} /></Field>
        <Field label="Quantity" htmlFor="xe-q"><NumField id="xe-q" value={n.quantity} onValue={(v) => setN((x) => ({ ...x, quantity: v }))} /></Field>
        <Field label="Unit rate" htmlFor="xe-r"><NumField id="xe-r" value={n.unit_rate} onValue={(v) => setN((x) => ({ ...x, unit_rate: v }))} /></Field>
        <Field label="Total amount" htmlFor="xe-a" error={tried ? errors.amount : ''} hint={n.quantity > 0 && n.unit_rate > 0 ? 'Quantity x rate' : undefined}><NumField id="xe-a" value={computed} disabled={n.quantity > 0 && n.unit_rate > 0} onValue={(v) => setN((x) => ({ ...x, amount: v }))} /></Field>
        <Field label="Vendor or payee" htmlFor="xe-v"><Input id="xe-v" value={f.vendor} onChange={set('vendor')} /></Field>
        <Field label="Invoice or voucher no." htmlFor="xe-i" hint="Each is recorded once"><Input id="xe-i" value={f.invoice_no} onChange={set('invoice_no')} /></Field>
        <Field label="Payment" htmlFor="xe-p"><Select id="xe-p" value={f.payment_status} onChange={set('payment_status')} options={['Unpaid', 'Part paid', 'Paid'].map((x) => ({ value: x, label: x }))} /></Field>
        <Field label="Payment reference" htmlFor="xe-pr" className="sm:col-span-2"><Input id="xe-pr" value={f.payment_ref} onChange={set('payment_ref')} /></Field>
      </div>
      <FormFoot error={save.error?.message} busy={save.isPending} label={e ? 'Save' : 'Record the expense'} onClose={onClose} onSave={() => (bad ? setTried(true) : save.mutate())} />
    </div>
  )
}
