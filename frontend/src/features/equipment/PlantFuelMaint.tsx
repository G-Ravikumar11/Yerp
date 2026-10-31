import { useState } from 'react'
import { Paperclip, Plus, Trash2 } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilesModal } from '@/components/data/FilesModal'
import { Badge, Button, Card, ConfirmDialog, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { approveMaint, completeMaint, plantKeys, raiseMaint, recordFuel, removeFuel, updateMaint, useFuel, useMaintenance, type FuelRow, type Maint } from '@/api/plant'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { FormFoot, LoadError, MachineSelect, RangeBar, StatusBadge, usePaged } from './plantParts'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import { FuelMonitor } from './PlantChecks'

// ---- fuel ----------------------------------------------------------------------------------------

export function Fuel() {
  const { can } = useSession()
  const [r, setR] = useState({ from: '', to: '', asset: 0 })
  const q = useFuel({ date_from: r.from, date_to: r.to, asset_id: r.asset })
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<FuelRow | null>(null)
  const [files, setFiles] = useState<FuelRow | null>(null)
  const del = useAction((f: FuelRow) => removeFuel(f.id), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: () => setRemoving(null) })
  const { shown, pager } = usePaged(q.data?.fuel)
  const cols: TableColumn<FuelRow>[] = [
    { id: 'n', header: 'Fuel ID', cell: (f) => <span className="font-mono text-[13px]">{f.number}</span> },
    { id: 'd', header: 'When', sort: (f) => f.filled_at, cell: (f) => <div>{formatDate(f.filled_at.slice(0, 10))}<div className="text-xs text-muted-foreground">{f.filled_at.slice(11, 16)}</div></div> },
    { id: 'm', header: 'Machine', cell: (f) => <div><span className="font-mono text-[13px]">{f.code}</span> {f.machine}<div className="text-xs text-muted-foreground">{f.project}</div></div> },
    { id: 'q', header: 'Litres', align: 'right', sort: (f) => f.litres, cell: (f) => <div>{f.litres}<div className="text-xs text-muted-foreground">{f.fuel_type} @ {f.rate}</div></div> },
    { id: 'a', header: 'Amount', align: 'right', sort: (f) => f.amount, cell: (f) => formatINR(f.amount) },
    { id: 's', header: 'Supplier / voucher', hideBelow: 'md', cell: (f) => <div>{f.supplier || '-'}<div className="text-xs text-muted-foreground">{f.voucher_no}</div></div> },
    { id: 'mt', header: 'Meter', hideBelow: 'lg', align: 'right', cell: (f) => f.meter_reading ?? '-' },
    { id: 'by', header: 'Recorded by', hideBelow: 'lg', cell: (f) => f.recorded_by },
    { id: 'act', header: '', align: 'right', cell: (f) => <div className="flex justify-end gap-1"><Button size="sm" variant="ghost" aria-label={`Attachments for ${f.number}`} onClick={() => setFiles(f)}><Paperclip /></Button>{can('stores.manage|workorders.manage') && <Button size="sm" variant="ghost" className="text-danger" aria-label={`Delete ${f.number}`} onClick={() => setRemoving(f)}><Trash2 /></Button>}</div> },
  ]
  const d = q.data
  return (
    <div>
      <RangeBar from={r.from} to={r.to} onChange={(from, to) => setR((x) => ({ ...x, from, to }))}>
        <div className="w-56"><MachineSelect id="fu-fm" value={r.asset} onChange={(asset) => setR((x) => ({ ...x, asset }))} placeholder="Every machine" /></div>
        {can('site.record|stores.manage') && <Button className="ml-auto" onClick={() => setAdding(true)}><Plus /> Record fuel</Button>}
      </RangeBar>
      <FuelMonitor from={r.from} to={r.to} asset={r.asset} />
      {q.isError ? <LoadError message={q.error.message} retry={() => q.refetch()} /> : <>
        {d && d.fuel.length > 0 && <p className="mb-2 text-[13px] text-muted-foreground"><strong className="text-foreground">{d.totals.litres} L</strong> for <strong className="text-foreground">{formatINR(d.totals.amount)}</strong> in {d.fuel.length} fills.</p>}
        <Card className="mb-4 overflow-hidden"><DataTable label="Fuel" className="rounded-none border-0 shadow-none" rows={shown} columns={cols} rowKey={(f) => f.id} loading={q.isPending} empty="No fuel recorded for these filters." />{!q.isPending && pager}</Card>
        {d && d.by_machine.length > 0 && (
          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="overflow-x-auto p-4"><h3 className="mb-2 text-sm font-semibold">By machine</h3>
              <table aria-label="Fuel by machine" className="w-full text-[13px]"><thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Machine</th><th className="text-right">Litres</th><th className="text-right">Amount</th><th className="text-right">Running h</th><th className="text-right">L / h</th><th className="text-right">Cost / h</th></tr></thead>
                <tbody>{d.by_machine.map((m) => <tr key={m.asset_id} className="border-t border-border"><td className="py-1.5">{m.code} {m.name}</td><td className="text-right tabular">{m.litres}</td><td className="text-right tabular">{formatINR(m.amount)}</td><td className="text-right tabular">{m.operating_hours}</td><td className="text-right tabular">{m.operating_hours ? m.litres_per_hour : '-'}</td><td className="text-right tabular">{m.operating_hours ? formatINR(m.cost_per_hour) : '-'}</td></tr>)}</tbody></table>
              <p className="mt-2 text-[11px] text-muted-foreground">Litres and cost an hour are worked out where the logbook has running hours for the same period.</p>
            </Card>
            <Card className="overflow-x-auto p-4"><h3 className="mb-2 text-sm font-semibold">By day</h3>
              <table aria-label="Fuel by day" className="w-full text-[13px]"><thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Day</th><th className="text-right">Litres</th><th className="text-right">Amount</th></tr></thead>
                <tbody>{d.by_day.slice(0, 31).map((x) => <tr key={x.day} className="border-t border-border"><td className="py-1.5">{formatDate(x.day)}</td><td className="text-right tabular">{Math.round(x.litres * 100) / 100}</td><td className="text-right tabular">{formatINR(x.amount)}</td></tr>)}</tbody></table>
            </Card>
          </div>
        )}
      </>}
      <FuelModal open={adding} types={d?.fuel_types ?? ['Diesel']} onClose={() => setAdding(false)} />
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={removing ? `Delete ${removing.number}?` : ''} description="Do you want to delete this? It cannot be undone." confirmLabel="Yes" cancelLabel="Cancel" tone="danger" loading={del.isPending} onConfirm={() => { if (removing) del.mutate(removing) }} />
      {files && <FilesModal type="plant_fuel" id={files.id} title={`${files.number} voucher`} onClose={() => setFiles(null)} />}
    </div>
  )
}

function FuelModal({ open, types, onClose }: { open: boolean; types: string[]; onClose: () => void }) {
  return <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Record fuel" description="The cost of fuel is counted here and only here." size="lg">{open && <FuelForm types={types} onClose={onClose} />}</Modal>
}

function FuelForm({ types, onClose }: { types: string[]; onClose: () => void }) {
  const [f, setF] = useState({ asset_id: 0, filled_on: today(), filled_time: new Date().toTimeString().slice(0, 5), fuel_type: 'Diesel', supplier: '', voucher_no: '', notes: '' })
  const [n, setN] = useState({ litres: 0, rate: 0, meter: 0 })
  const [useMeter, setUseMeter] = useState(false)
  const [tried, setTried] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const amount = Math.round(n.litres * n.rate * 100) / 100
  const errors = { asset: f.asset_id ? '' : 'Choose the machine.', litres: n.litres > 0 && n.litres <= 5000 ? '' : 'Litres, more than 0 and at most 5,000.', rate: n.rate > 0 ? '' : 'The price a litre.', date: f.filled_on > today() ? 'Not in the future.' : '' }
  const bad = Object.values(errors).some(Boolean)
  const save = useAction(() => recordFuel({ ...f, litres: n.litres, rate: n.rate, amount, meter_reading: useMeter ? n.meter : null }), { invalidate: [plantKeys.all], success: (r) => [r.message, r.warning].filter(Boolean).join(' '), onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Machine" htmlFor="fl-m" error={tried ? errors.asset : ''} className="sm:col-span-3"><MachineSelect id="fl-m" value={f.asset_id} onChange={(v) => setF((x) => ({ ...x, asset_id: v }))} /></Field>
        <Field label="Date" htmlFor="fl-d" error={tried ? errors.date : ''}><Input id="fl-d" type="date" max={today()} value={f.filled_on} onChange={set('filled_on')} /></Field>
        <Field label="Time" htmlFor="fl-t"><Input id="fl-t" type="time" value={f.filled_time} onChange={set('filled_time')} /></Field>
        <Field label="Fuel type" htmlFor="fl-ty"><Select id="fl-ty" value={f.fuel_type} onChange={set('fuel_type')} options={types.map((t) => ({ value: t, label: t }))} /></Field>
        <Field label="Quantity (litres)" htmlFor="fl-l" error={tried ? errors.litres : ''}><NumField id="fl-l" value={n.litres} onValue={(v) => setN((x) => ({ ...x, litres: v }))} /></Field>
        <Field label="Price a litre" htmlFor="fl-r" error={tried ? errors.rate : ''}><NumField id="fl-r" value={n.rate} onValue={(v) => setN((x) => ({ ...x, rate: v }))} /></Field>
        <Field label="Total cost" htmlFor="fl-a"><Input id="fl-a" readOnly value={formatINR(amount)} /></Field>
        <Field label="Supplier" htmlFor="fl-s"><Input id="fl-s" value={f.supplier} onChange={set('supplier')} /></Field>
        <Field label="Issue voucher or invoice no." htmlFor="fl-v" hint="Each voucher is recorded once"><Input id="fl-v" value={f.voucher_no} onChange={set('voucher_no')} /></Field>
        <Field label="Meter at refuelling" htmlFor="fl-mt"><div className="flex items-center gap-2"><input type="checkbox" aria-label="Record the meter" checked={useMeter} onChange={(e) => setUseMeter(e.target.checked)} /><NumField id="fl-mt" value={n.meter} disabled={!useMeter} onValue={(v) => setN((x) => ({ ...x, meter: v }))} /></div></Field>
        <Field label="Notes" htmlFor="fl-n" className="sm:col-span-3"><Textarea id="fl-n" rows={2} value={f.notes} onChange={set('notes')} /></Field>
      </div>
      <FormFoot error={save.error?.message} busy={save.isPending} label="Record fuel" onClose={onClose} onSave={() => (bad ? setTried(true) : save.mutate())} />
    </div>
  )
}

// ---- maintenance ------------------------------------------------------------------------------------

export function Maintenance() {
  const { can } = useSession()
  const [r, setR] = useState({ from: '', to: '', asset: 0, status: 'open' })
  const q = useMaintenance({ date_from: r.from, date_to: r.to, asset_id: r.asset, status: r.status })
  const [raising, setRaising] = useState(false)
  const [doing, setDoing] = useState<Maint | null>(null)
  const [completing, setCompleting] = useState<Maint | null>(null)
  const [files, setFiles] = useState<Maint | null>(null)
  const start = useAction((m: Maint) => updateMaint(m.id, { status: 'In progress' }), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: () => setDoing(null) })
  const approve = useAction((m: Maint) => approveMaint(m.id), { invalidate: [plantKeys.all], success: (x) => x.message })
  const { shown, pager } = usePaged(q.data?.maintenance)
  const cols: TableColumn<Maint>[] = [
    { id: 'n', header: 'Request', cell: (m) => <div><span className="font-mono text-[13px]">{m.number}</span><div className="text-xs text-muted-foreground">{m.kind}</div></div> },
    { id: 'm', header: 'Machine', cell: (m) => <div><span className="font-mono text-[13px]">{m.code}</span> {m.machine}<div className="mt-0.5"><StatusBadge status={m.availability} /></div></div> },
    { id: 'w', header: 'Problem / work', cell: (m) => <div className="max-w-72"><span className="line-clamp-2">{m.description}</span>{m.work_performed && <div className="text-xs text-success">Done: {m.work_performed}</div>}</div> },
    { id: 'p', header: 'Priority', hideBelow: 'md', cell: (m) => <Badge tone={m.priority === 'Urgent' ? 'danger' : m.priority === 'High' ? 'warning' : 'neutral'}>{m.priority}</Badge> },
    { id: 'd', header: 'Dates', hideBelow: 'md', sort: (m) => m.reported_on, cell: (m) => <div className="text-[13px]">Reported {formatDate(m.reported_on)}{m.scheduled_on && <div className={m.overdue ? 'font-semibold text-danger' : 'text-muted-foreground'}>Due {formatDate(m.scheduled_on)}</div>}{m.completed_on && <div className="text-muted-foreground">Done {formatDate(m.completed_on)}</div>}</div> },
    { id: 'c', header: 'Cost / down', align: 'right', hideBelow: 'lg', cell: (m) => <div>{m.total_cost ? formatINR(m.total_cost) : '-'}<div className="text-xs text-muted-foreground">{m.downtime_hours ? `${m.downtime_hours} h down` : ''}</div></div> },
    { id: 's', header: 'Status', cell: (m) => <div><Badge tone={m.status === 'Completed' ? 'success' : m.status === 'In progress' ? 'info' : m.overdue ? 'danger' : 'warning'} dot>{m.overdue ? 'Overdue' : m.status}</Badge>{m.approval_status && <div className="text-xs text-success">{m.approval_status}</div>}</div> },
    {
      id: 'act', header: '', align: 'right',
      cell: (m) => (
        <div className="flex justify-end gap-1.5">
          {m.status !== 'Completed' && m.status !== 'In progress' && can('site.record') && <Button size="sm" variant="outline" onClick={() => setDoing(m)}>Start work</Button>}
          {m.status !== 'Completed' && can('site.record') && <Button size="sm" onClick={() => setCompleting(m)}>Complete</Button>}
          {m.status === 'Completed' && !m.approval_status && can('site.signoff') && <Button size="sm" variant="outline" loading={approve.isPending && approve.variables?.id === m.id} onClick={() => approve.mutate(m)}>Approve</Button>}
          <Button size="sm" variant="ghost" aria-label={`Documents for ${m.number}`} onClick={() => setFiles(m)}><Paperclip /></Button>
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (m) => <MasterDelete kind="service" id={m.id} label={m.number} noun="service record" /> },
  ]
  return (
    <div>
      <RangeBar from={r.from} to={r.to} onChange={(from, to) => setR((x) => ({ ...x, from, to }))}>
        <div className="w-56"><MachineSelect id="mt-fm" value={r.asset} onChange={(asset) => setR((x) => ({ ...x, asset }))} placeholder="Every machine" /></div>
        <div className="w-40"><Select aria-label="Status" value={r.status} placeholder="All, with history" onChange={(e) => setR((x) => ({ ...x, status: e.target.value }))} options={[{ value: 'open', label: 'Open' }, { value: 'Requested', label: 'Requested' }, { value: 'Scheduled', label: 'Scheduled' }, { value: 'In progress', label: 'In progress' }, { value: 'Completed', label: 'Completed' }]} /></div>
        {can('site.record') && <Button className="ml-auto" onClick={() => setRaising(true)}><Plus /> Report or schedule</Button>}
      </RangeBar>
      {q.isError ? <LoadError message={q.error.message} retry={() => q.refetch()} /> : (
        <Card className="overflow-hidden"><DataTable label="Maintenance" className="rounded-none border-0 shadow-none" rows={shown} columns={cols} rowKey={(m) => m.id} loading={q.isPending} empty={r.status === 'open' ? 'No open maintenance.' : 'No maintenance for these filters.'} />{!q.isPending && pager}</Card>
      )}
      <RaiseModal open={raising} onClose={() => setRaising(false)} />
      <CompleteModal job={completing} onClose={() => setCompleting(null)} />
      <ConfirmDialog open={!!doing} onOpenChange={(o) => !o && setDoing(null)} title={doing ? `Start work on ${doing.number}?` : ''} description="The machine shows as under maintenance until the job is completed." confirmLabel="Yes" cancelLabel="Cancel" loading={start.isPending} onConfirm={() => { if (doing) start.mutate(doing) }} />
      {files && <FilesModal type="plant_maintenance" id={files.id} title={`${files.number} invoices and documents`} onClose={() => setFiles(null)} />}
    </div>
  )
}

function RaiseModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Report a problem or schedule a service" size="lg">{open && <RaiseForm onClose={onClose} />}</Modal>
}

function RaiseForm({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState({ asset_id: 0, kind: 'Corrective', priority: 'Normal', reported_on: today(), scheduled_on: '', description: '', mechanic: '' })
  const [down, setDown] = useState(false)
  const [tried, setTried] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const errors = { asset: f.asset_id ? '' : 'Choose the machine.', desc: f.description.trim() ? '' : 'Describe the problem or the work.', sch: f.scheduled_on && f.scheduled_on < f.reported_on ? 'Not before it was reported.' : '' }
  const bad = Object.values(errors).some(Boolean)
  const save = useAction(() => raiseMaint({ ...f, out_of_service: down }), { invalidate: [plantKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Machine" htmlFor="mr-m" error={tried ? errors.asset : ''} className="sm:col-span-3"><MachineSelect id="mr-m" value={f.asset_id} onChange={(v) => setF((x) => ({ ...x, asset_id: v }))} /></Field>
        <Field label="Type" htmlFor="mr-k"><Select id="mr-k" value={f.kind} onChange={set('kind')} options={['Preventive', 'Corrective', 'Emergency'].map((x) => ({ value: x, label: x }))} /></Field>
        <Field label="Priority" htmlFor="mr-p"><Select id="mr-p" value={f.priority} onChange={set('priority')} options={['Low', 'Normal', 'High', 'Urgent'].map((x) => ({ value: x, label: x }))} /></Field>
        <Field label="Reported" htmlFor="mr-r"><Input id="mr-r" type="date" max={today()} value={f.reported_on} onChange={set('reported_on')} /></Field>
        <Field label="Problem description" htmlFor="mr-d" error={tried ? errors.desc : ''} className="sm:col-span-3"><Textarea id="mr-d" rows={3} value={f.description} onChange={set('description')} /></Field>
        <Field label="Mechanic or service provider" htmlFor="mr-mc" className="sm:col-span-2"><Input id="mr-mc" value={f.mechanic} onChange={set('mechanic')} /></Field>
        <Field label="Scheduled for" htmlFor="mr-s" error={errors.sch}><Input id="mr-s" type="date" min={f.reported_on} value={f.scheduled_on} onChange={set('scheduled_on')} /></Field>
        {f.kind !== 'Preventive' && <label className="flex items-center gap-2 text-sm sm:col-span-3"><input type="checkbox" checked={down} onChange={(e) => setDown(e.target.checked)} /> It has broken down - take it off work now</label>}
      </div>
      <FormFoot error={save.error?.message} busy={save.isPending} label="Raise it" onClose={onClose} onSave={() => (bad ? setTried(true) : save.mutate())} />
    </div>
  )
}

function CompleteModal({ job, onClose }: { job: Maint | null; onClose: () => void }) {
  return <Modal open={!!job} onOpenChange={(o) => !o && onClose()} title={job ? `Complete ${job.number} - ${job.code} ${job.machine}` : ''} description="What was done, what it cost, how long it was down, and when it is next due." size="lg">{job && <CompleteForm job={job} onClose={onClose} />}</Modal>
}

function CompleteForm({ job: m, onClose }: { job: Maint; onClose: () => void }) {
  const [f, setF] = useState({ completed_on: today(), work_performed: '', parts_used: m.parts_used, downtime_start: m.downtime_start.replace(' ', 'T'), downtime_end: '', invoice_no: m.invoice_no, next_service_on: '' })
  const [n, setN] = useState({ parts: m.parts_cost, labour: m.labour_cost, next_meter: 0 })
  const [tried, setTried] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const errors = { work: f.work_performed.trim() ? '' : 'Say what was done.', down: f.downtime_start && f.downtime_end && f.downtime_end < f.downtime_start ? 'Downtime ends before it started.' : '', next: f.next_service_on && f.next_service_on <= f.completed_on ? 'The next service is after this one.' : '' }
  const bad = Object.values(errors).some(Boolean)
  const save = useAction(() => completeMaint(m.id, { ...f, downtime_start: f.downtime_start.replace('T', ' '), downtime_end: f.downtime_end.replace('T', ' '), parts_cost: n.parts, labour_cost: n.labour, next_service_meter: n.next_meter || null }), { invalidate: [plantKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <div>
      <p className="mb-3 text-[13px] text-muted-foreground">{m.description}</p>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Work performed" htmlFor="mc-w" error={tried ? errors.work : ''} className="sm:col-span-3"><Textarea id="mc-w" rows={2} value={f.work_performed} onChange={set('work_performed')} /></Field>
        <Field label="Spare parts used" htmlFor="mc-p" className="sm:col-span-3"><Input id="mc-p" value={f.parts_used} onChange={set('parts_used')} /></Field>
        <Field label="Parts cost" htmlFor="mc-pc"><NumField id="mc-pc" value={n.parts} onValue={(v) => setN((x) => ({ ...x, parts: v }))} /></Field>
        <Field label="Labour and repair cost" htmlFor="mc-lc"><NumField id="mc-lc" value={n.labour} onValue={(v) => setN((x) => ({ ...x, labour: v }))} /></Field>
        <Field label="Invoice no." htmlFor="mc-i"><Input id="mc-i" value={f.invoice_no} onChange={set('invoice_no')} /></Field>
        <Field label="Down from" htmlFor="mc-ds"><Input id="mc-ds" type="datetime-local" value={f.downtime_start} onChange={set('downtime_start')} /></Field>
        <Field label="Down until" htmlFor="mc-de" error={errors.down}><Input id="mc-de" type="datetime-local" value={f.downtime_end} onChange={set('downtime_end')} /></Field>
        <Field label="Completed on" htmlFor="mc-c"><Input id="mc-c" type="date" max={today()} value={f.completed_on} onChange={set('completed_on')} /></Field>
        <Field label="Next service date" htmlFor="mc-ns" error={errors.next}><Input id="mc-ns" type="date" value={f.next_service_on} onChange={set('next_service_on')} /></Field>
        <Field label="Or at meter reading" htmlFor="mc-nm"><NumField id="mc-nm" value={n.next_meter} onValue={(v) => setN((x) => ({ ...x, next_meter: v }))} /></Field>
      </div>
      <FormFoot error={save.error?.message} busy={save.isPending} label="Complete the job" onClose={onClose} onSave={() => (bad ? setTried(true) : save.mutate())} />
    </div>
  )
}
