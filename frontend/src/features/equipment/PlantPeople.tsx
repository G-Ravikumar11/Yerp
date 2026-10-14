import { useMemo, useState } from 'react'
import { Plus } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, ConfirmDialog, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { allocate, decideLog, endAllocation, plantKeys, reassign, saveHoursRule, saveLog, useAllocations, useLogs, usePeople, type Allocation, type LogRow } from '@/api/plant'
import { useRegister } from '@/api/equipment'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { FormFoot, LoadError, MachineSelect, PersonSelect, RangeBar, StatusBadge, usePaged } from './plantParts'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

// ---- allocation ------------------------------------------------------------------------------------

/** Who works which machine, in which shift, from when - and who did before. */
export function Allocations() {
  const { can } = useSession()
  const manage = can('stores.manage|workorders.manage|site.signoff')
  const [status, setStatus] = useState('Active')
  const [q, setQ] = useState('')
  const list = useAllocations({ status })
  const [adding, setAdding] = useState(false)
  const [moving, setMoving] = useState<Allocation | null>(null)
  const [ending, setEnding] = useState<Allocation | null>(null)
  const end = useAction((v: { a: Allocation; reason: string }) => endAllocation(v.a.id, v.reason), { invalidate: [plantKeys.all], success: (r) => r.message, onSuccess: () => setEnding(null) })
  const rows = useMemo(() => (list.data?.allocations ?? []).filter((a) => !q || `${a.code} ${a.machine} ${a.employee?.name} ${a.employee?.code} ${a.project}`.toLowerCase().includes(q.toLowerCase())), [list.data, q])
  const { shown, pager } = usePaged(rows)
  const cols: TableColumn<Allocation>[] = [
    { id: 'm', header: 'Machine', sort: (a) => a.code, cell: (a) => <div><span className="font-mono text-[13px] font-semibold">{a.code}</span> {a.machine}<div className="mt-0.5"><StatusBadge status={a.availability} /></div></div> },
    { id: 'p', header: 'Employee', sort: (a) => a.employee?.name ?? '', cell: (a) => <div className="font-medium">{a.employee?.name}<div className="text-xs text-muted-foreground">{[a.employee?.code, a.employee?.designation].filter(Boolean).join(' - ')}</div></div> },
    { id: 'mob', header: 'Mobile', hideBelow: 'md', cell: (a) => a.employee?.mobile ? <a className="text-primary hover:underline" href={`tel:${a.employee.mobile}`}>{a.employee.mobile}</a> : '-' },
    { id: 'role', header: 'Role / shift', cell: (a) => <div>{a.role}<div className="text-xs text-muted-foreground">{a.shift} shift</div></div> },
    { id: 'site', header: 'Project', hideBelow: 'lg', cell: (a) => a.project || 'Yard' },
    { id: 'dates', header: 'Dates', hideBelow: 'md', sort: (a) => a.start_date, cell: (a) => <div className="text-[13px]">{formatDate(a.start_date)} - {a.end_date ? formatDate(a.end_date) : 'open'}{a.ended_reason && <div className="text-xs text-muted-foreground">{a.ended_reason}</div>}</div> },
    { id: 'sup', header: 'Supervisor', hideBelow: 'lg', cell: (a) => a.supervisor?.name ?? '-' },
    { id: 'st', header: 'Status', cell: (a) => <Badge tone={a.status === 'Active' ? 'success' : 'neutral'} dot>{a.status}</Badge> },
    { id: 'act', header: '', align: 'right', cell: (a) => manage && a.status === 'Active' ? <div className="flex justify-end gap-1.5"><Button size="sm" variant="outline" onClick={() => setMoving(a)}>Reassign</Button><Button size="sm" variant="ghost" className="text-danger" onClick={() => setEnding(a)}>End</Button></div> : null },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (a) => <MasterDelete kind="allocation" id={a.id} label={`${a.code} ${a.machine}`} noun="allocation" /> },
  ]
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input aria-label="Search allocations" className="min-w-52 flex-1 basis-56" placeholder="Search machine, employee or project" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="w-40"><Select aria-label="Status" value={status} placeholder="All, with history" onChange={(e) => setStatus(e.target.value)} options={[{ value: 'Active', label: 'Active' }, { value: 'Ended', label: 'Ended' }]} /></div>
        {manage && <Button className="ml-auto" onClick={() => setAdding(true)}><Plus /> Allocate</Button>}
      </div>
      {list.isError ? <LoadError message={list.error.message} retry={() => list.refetch()} /> : (
        <Card className="overflow-hidden"><DataTable label="Allocations" className="rounded-none border-0 shadow-none" rows={shown} columns={cols} rowKey={(a) => a.id} loading={list.isPending} empty={q ? 'Nobody matches.' : 'Nobody is allocated to a machine yet.'} />{!list.isPending && pager}</Card>
      )}
      <AllocateModal open={adding} onClose={() => setAdding(false)} />
      <ReassignModal allocation={moving} onClose={() => setMoving(null)} />
      <ConfirmDialog open={!!ending} onOpenChange={(o) => !o && setEnding(null)} title={ending ? `End ${ending.employee?.name} on ${ending.code}?` : ''} description="It stays in the history." reason={{ label: 'Why (optional)' }} confirmLabel="Yes" cancelLabel="Cancel" tone="danger" loading={end.isPending} onConfirm={(reason) => { if (ending) end.mutate({ a: ending, reason }) }} />
    </div>
  )
}

function AllocateModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Allocate an employee to a machine" description="Several people may work one machine in different shifts, or alongside its operator.">{open && <AllocateForm onClose={onClose} />}</Modal>
}

function AllocateForm({ onClose }: { onClose: () => void }) {
  const meta = usePeople()
  const [f, setF] = useState({ asset_id: 0, employee_id: 0, supervisor_id: 0, role: 'Operator', shift: 'Day', start_date: today(), end_date: '', notes: '' })
  const [tried, setTried] = useState(false)
  const set = (k: keyof typeof f) => (v: string | number) => setF((x) => ({ ...x, [k]: v }))
  const errors = { asset: f.asset_id ? '' : 'Choose the machine.', emp: f.employee_id ? '' : 'Choose the employee.', end: f.end_date && f.end_date < f.start_date ? 'It cannot end before it starts.' : '' }
  const bad = Object.values(errors).some(Boolean)
  const person = meta.data?.employees.find((p) => p.id === f.employee_id)
  const save = useAction(() => allocate({ ...f, supervisor_id: f.supervisor_id || null }), { invalidate: [plantKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Machine" htmlFor="al-m" error={tried ? errors.asset : ''} className="sm:col-span-2"><MachineSelect id="al-m" value={f.asset_id} onChange={set('asset_id')} filter={(m) => !['Breakdown', 'Under repair', 'Returned'].includes(m.status)} /></Field>
        <Field label="Employee" htmlFor="al-e" error={tried ? errors.emp : ''} hint={person ? `${person.mobile || 'No mobile on record'} - ${person.designation || 'no designation'}${person.on_machines?.length ? ` - already on ${person.on_machines.join(', ')}` : ''}` : undefined}><PersonSelect id="al-e" value={f.employee_id} onChange={set('employee_id')} /></Field>
        <Field label="Job role" htmlFor="al-r"><Select id="al-r" value={f.role} onChange={(e) => set('role')(e.target.value)} options={(meta.data?.roles ?? ['Operator']).map((r) => ({ value: r, label: r }))} /></Field>
        <Field label="Shift" htmlFor="al-s"><Select id="al-s" value={f.shift} onChange={(e) => set('shift')(e.target.value)} options={(meta.data?.shifts ?? ['Day']).map((r) => ({ value: r, label: r }))} /></Field>
        <Field label="Supervisor" htmlFor="al-sup"><PersonSelect id="al-sup" value={f.supervisor_id} onChange={set('supervisor_id')} placeholder="Nobody named" /></Field>
        <Field label="Start date" htmlFor="al-sd"><Input id="al-sd" type="date" value={f.start_date} onChange={(e) => set('start_date')(e.target.value)} /></Field>
        <Field label="End date" htmlFor="al-ed" hint="Leave open if it runs on" error={errors.end}><Input id="al-ed" type="date" min={f.start_date} value={f.end_date} onChange={(e) => set('end_date')(e.target.value)} /></Field>
        <Field label="Notes" htmlFor="al-n" className="sm:col-span-2"><Textarea id="al-n" rows={2} value={f.notes} onChange={(e) => set('notes')(e.target.value)} /></Field>
      </div>
      <FormFoot error={save.error?.message} busy={save.isPending} label="Allocate" onClose={onClose} onSave={() => (bad ? setTried(true) : save.mutate())} />
    </div>
  )
}

function ReassignModal({ allocation: a, onClose }: { allocation: Allocation | null; onClose: () => void }) {
  return <Modal open={!!a} onOpenChange={(o) => !o && onClose()} title={a ? `Reassign ${a.code} ${a.machine}` : ''} description={a ? `${a.role}, ${a.shift.toLowerCase()} shift - now ${a.employee?.name}. Both stay in the history.` : ''}>{a && <ReassignForm a={a} onClose={onClose} />}</Modal>
}

function ReassignForm({ a, onClose }: { a: Allocation; onClose: () => void }) {
  const [emp, setEmp] = useState(0)
  const [on, setOn] = useState(today())
  const [reason, setReason] = useState('')
  const save = useAction(() => reassign(a.id, emp, on, reason), { invalidate: [plantKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4">
        <Field label="New employee" htmlFor="ra-e"><PersonSelect id="ra-e" value={emp} onChange={setEmp} /></Field>
        <Field label="From" htmlFor="ra-on"><Input id="ra-on" type="date" min={a.start_date} value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Reason" htmlFor="ra-r"><Input id="ra-r" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </div>
      <FormFoot error={save.error?.message} busy={save.isPending} label="Reassign" onClose={onClose} onSave={() => emp && save.mutate()} />
    </div>
  )
}

// ---- logbook ---------------------------------------------------------------------------------------

const toMin = (t: string) => { const m = /^(\d{1,2}):(\d{2})$/.exec(t); return m ? Number(m[1]) * 60 + Number(m[2]) : null }

/** Each person's shift on each machine: their hours on duty, and - separately - the hours the machine ran. */
export function Logbook() {
  const { can } = useSession()
  const [r, setR] = useState({ from: '', to: '', asset: 0, emp: 0, status: '' })
  const q = useLogs({ date_from: r.from, date_to: r.to, asset_id: r.asset, employee_id: r.emp, status: r.status })
  const [editing, setEditing] = useState<LogRow | 'new' | null>(null)
  const [rejecting, setRejecting] = useState<LogRow | null>(null)
  const [rule, setRule] = useState(false)
  const decide = useAction((v: { l: LogRow; d: 'approve' | 'reject'; remarks: string }) => decideLog(v.l.id, v.d, v.remarks), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: () => setRejecting(null) })
  const { shown, pager } = usePaged(q.data?.logs)
  const rows = q.data?.logs ?? []
  const sum = (k: 'attendance_hours' | 'operating_hours' | 'overtime_hours' | 'idle_hours') => Math.round(rows.reduce((n, l) => n + l[k], 0) * 10) / 10
  const cols: TableColumn<LogRow>[] = [
    { id: 'd', header: 'Date / shift', sort: (l) => l.log_date, cell: (l) => <div>{formatDate(l.log_date)}<div className="text-xs text-muted-foreground">{l.shift || '-'} {l.start_time && `${l.start_time}-${l.end_time}`}</div></div> },
    { id: 'p', header: 'Employee', cell: (l) => <div>{l.employee?.name ?? '-'}<div className="text-xs text-muted-foreground">{l.employee?.mobile}</div></div> },
    { id: 'm', header: 'Machine', cell: (l) => <div><span className="font-mono text-[13px]">{l.code}</span> {l.machine}<div className="text-xs text-muted-foreground">{l.project}</div></div> },
    { id: 'duty', header: 'On duty', align: 'right', hideBelow: 'md', cell: (l) => <div>{l.attendance_hours} h<div className="text-xs text-muted-foreground">{l.regular_hours} + {l.overtime_hours} OT</div></div> },
    { id: 'mach', header: 'Machine h', align: 'right', cell: (l) => <div>{l.operating_hours}<div className="text-xs text-muted-foreground">idle {l.idle_hours}{l.breakdown_hours ? ` - down ${l.breakdown_hours}` : ''}</div></div> },
    { id: 'meter', header: 'Meter', align: 'right', hideBelow: 'lg', cell: (l) => (l.opening_meter != null ? `${l.opening_meter} - ${l.closing_meter}` : '-') },
    { id: 'st', header: 'Status', cell: (l) => <div><Badge tone={l.approval_status === 'Approved' ? 'success' : l.approval_status === 'Rejected' ? 'danger' : 'warning'} dot>{l.approval_status}</Badge>{l.supervisor_remarks && <div className="mt-0.5 max-w-40 truncate text-xs text-muted-foreground" title={l.supervisor_remarks}>{l.supervisor_remarks}</div>}</div> },
    {
      id: 'act', header: '', align: 'right',
      cell: (l) => (
        <div className="flex justify-end gap-1.5">
          {can('site.signoff') && l.approval_status === 'Submitted' && <><Button size="sm" onClick={() => decide.mutate({ l, d: 'approve', remarks: '' })}>Approve</Button><Button size="sm" variant="ghost" className="text-danger" onClick={() => setRejecting(l)}>Reject</Button></>}
          {can('site.record') && l.start_time && (l.approval_status !== 'Approved' || can('site.signoff')) && <Button size="sm" variant="outline" onClick={() => setEditing(l)}>Correct</Button>}
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (l) => <MasterDelete kind="machine_log" id={l.id} label={`${l.code} on ${formatDate(l.log_date)}`} noun="machine log" /> },
  ]
  return (
    <div>
      <RangeBar from={r.from} to={r.to} onChange={(from, to) => setR((x) => ({ ...x, from, to }))}>
        <div className="w-52"><MachineSelect id="lg-fm" value={r.asset} onChange={(asset) => setR((x) => ({ ...x, asset }))} placeholder="Every machine" /></div>
        <div className="w-52"><PersonSelect id="lg-fe" value={r.emp} onChange={(emp) => setR((x) => ({ ...x, emp }))} placeholder="Every employee" /></div>
        <div className="w-36"><Select aria-label="Approval" value={r.status} placeholder="Any status" onChange={(e) => setR((x) => ({ ...x, status: e.target.value }))} options={['Submitted', 'Approved', 'Rejected'].map((s) => ({ value: s, label: s }))} /></div>
        <span className="ml-auto flex gap-2">
          {can('stores.manage|workorders.manage') && <Button variant="outline" onClick={() => setRule(true)}>Overtime after {q.data?.regular_hours ?? 8} h</Button>}
          {can('site.record') && <Button onClick={() => setEditing('new')}><Plus /> Log a shift</Button>}
        </span>
      </RangeBar>
      {rows.length > 0 && <p className="mb-2 text-[13px] text-muted-foreground">{rows.length} shifts: <strong className="text-foreground">{sum('attendance_hours')} h</strong> on duty ({sum('overtime_hours')} overtime), machines ran <strong className="text-foreground">{sum('operating_hours')} h</strong>, idle {sum('idle_hours')} h.</p>}
      {q.isError ? <LoadError message={q.error.message} retry={() => q.refetch()} /> : (
        <Card className="overflow-hidden"><DataTable label="Logbook" className="rounded-none border-0 shadow-none" rows={shown} columns={cols} rowKey={(l) => l.id} loading={q.isPending} empty="No shifts logged for these filters." />{!q.isPending && pager}</Card>
      )}
      <LogModal log={editing} onClose={() => setEditing(null)} />
      <ConfirmDialog open={!!rejecting} onOpenChange={(o) => !o && setRejecting(null)} title="Reject this day?" reason={{ label: 'What is wrong with it', required: true }} confirmLabel="Reject" cancelLabel="Cancel" tone="danger" loading={decide.isPending} onConfirm={(remarks) => { if (rejecting) decide.mutate({ l: rejecting, d: 'reject', remarks }) }} />
      <RuleModal open={rule} current={q.data?.regular_hours ?? 8} onClose={() => setRule(false)} />
    </div>
  )
}

function RuleModal({ open, current, onClose }: { open: boolean; current: number; onClose: () => void }) {
  const [h, setH] = useState(current)
  const save = useAction(() => saveHoursRule(h), { invalidate: [plantKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Working-hour rule" description="Hours on duty up to this are regular; beyond it, overtime. It applies to shifts logged from now.">
      {open && <><Field label="Regular hours a shift" htmlFor="rule-h"><NumField id="rule-h" value={h} onValue={setH} /></Field><FormFoot error={save.error?.message} busy={save.isPending} label="Save" onClose={onClose} onSave={() => save.mutate()} /></>}
    </Modal>
  )
}

function LogModal({ log, onClose }: { log: LogRow | 'new' | null; onClose: () => void }) {
  const edit = log && log !== 'new' ? log : null
  return <Modal open={!!log} onOpenChange={(o) => !o && onClose()} title={edit ? `Correct ${edit.code} on ${formatDate(edit.log_date)}` : 'Log a shift'} description="The employee's time on duty and the machine's running hours are worked out separately." size="lg">{log && <LogForm log={edit} onClose={onClose} />}</Modal>
}

function LogForm({ log: l, onClose }: { log: LogRow | null; onClose: () => void }) {
  const machines = useRegister('')
  const people = usePeople()
  const [f, setF] = useState({
    asset_id: l?.asset_id ?? 0, employee_id: (l?.employee as { id?: number } | null)?.id ?? 0, log_date: l?.log_date ?? today(), shift: l?.shift || 'Day',
    start_time: l?.start_time ?? '07:00', end_time: l?.end_time ?? '17:00', work_done: l?.work_done ?? '', supervisor_remarks: l?.supervisor_remarks ?? '', correction_reason: '',
  })
  const [n, setN] = useState({ break_minutes: l?.break_minutes ?? 60, opening: l?.opening_meter ?? 0, closing: l?.closing_meter ?? 0, operating: l?.operating_hours ?? 0, breakdown: l?.breakdown_hours ?? 0, fuel: l?.fuel_litres ?? 0 })
  const [meters, setMeters] = useState(l ? l.opening_meter != null : true)
  const [tried, setTried] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const num = (k: keyof typeof n) => (v: number) => setN((x) => ({ ...x, [k]: v }))
  const m = machines.data?.assets.find((x) => x.id === f.asset_id)
  const p = people.data?.employees.find((x) => x.id === f.employee_id)
  // The same sums as the server, shown as they are typed.
  const s = toMin(f.start_time), e0 = toMin(f.end_time)
  const span = s != null && e0 != null ? (e0 <= s ? e0 + 1440 : e0) - s : null
  const duty = span != null ? Math.max(0, (span - n.break_minutes) / 60) : null
  const running = meters ? Math.max(0, n.closing - n.opening) : n.operating
  const errors = {
    asset: f.asset_id ? '' : 'Choose the machine.', emp: f.employee_id ? '' : 'Choose the employee.',
    time: span == null ? 'Times as 07:00.' : n.break_minutes >= span ? 'The break is longer than the shift.' : '',
    meter: meters && n.closing < n.opening ? 'The closing reading is below the opening one.' : '',
    over: span != null && running + n.breakdown > span / 60 + 0.01 ? 'Running and breakdown hours are longer than the shift.' : '',
    why: l && !f.correction_reason.trim() ? 'Say why it is being corrected.' : '',
  }
  const bad = Object.values(errors).some(Boolean)
  const save = useAction(() => saveLog(l?.id ?? null, {
    ...f, break_minutes: n.break_minutes, opening_meter: meters ? n.opening : null, closing_meter: meters ? n.closing : null, operating_hours: meters ? null : n.operating,
    breakdown_hours: n.breakdown, fuel_litres: n.fuel,
  }), { invalidate: [plantKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Machine" htmlFor="lb-m" error={tried ? errors.asset : ''} className="sm:col-span-2"><MachineSelect id="lb-m" value={f.asset_id} onChange={(v) => { setF((x) => ({ ...x, asset_id: v })); const mm = machines.data?.assets.find((x) => x.id === v); if (mm && !l) setN((x) => ({ ...x, opening: mm.meter_reading, closing: mm.meter_reading })) }} /></Field>
        <Field label="Work date" htmlFor="lb-d"><Input id="lb-d" type="date" max={today()} value={f.log_date} onChange={set('log_date')} /></Field>
        <Field label="Employee" htmlFor="lb-e" error={tried ? errors.emp : ''} hint={p ? `Mobile ${p.mobile || 'not on record'}` : undefined} className="sm:col-span-2"><PersonSelect id="lb-e" value={f.employee_id} onChange={(v) => setF((x) => ({ ...x, employee_id: v }))} /></Field>
        <Field label="Shift" htmlFor="lb-s"><Select id="lb-s" value={f.shift} onChange={set('shift')} options={['Day', 'Night', 'General'].map((x) => ({ value: x, label: x }))} /></Field>
        <Field label="Start time" htmlFor="lb-st" error={tried ? errors.time : ''}><Input id="lb-st" type="time" value={f.start_time} onChange={set('start_time')} /></Field>
        <Field label="End time" htmlFor="lb-et" hint={span != null && toMin(f.end_time)! <= toMin(f.start_time)! ? 'Next morning' : undefined}><Input id="lb-et" type="time" value={f.end_time} onChange={set('end_time')} /></Field>
        <Field label="Break (minutes)" htmlFor="lb-b"><NumField id="lb-b" value={n.break_minutes} onValue={num('break_minutes')} /></Field>
        <label className="flex items-center gap-2 text-sm sm:col-span-3"><input type="checkbox" checked={meters} onChange={(e) => setMeters(e.target.checked)} /> Read from the hour meter{m ? ` (it reads ${m.meter_reading} now)` : ''}</label>
        {meters ? <>
          <Field label="Opening meter" htmlFor="lb-om"><NumField id="lb-om" value={n.opening} onValue={num('opening')} /></Field>
          <Field label="Closing meter" htmlFor="lb-cm" error={errors.meter}><NumField id="lb-cm" value={n.closing} onValue={num('closing')} /></Field>
        </> : <Field label="Machine running hours" htmlFor="lb-oh"><NumField id="lb-oh" value={n.operating} onValue={num('operating')} /></Field>}
        <Field label="Breakdown hours" htmlFor="lb-bh" error={errors.over}><NumField id="lb-bh" value={n.breakdown} onValue={num('breakdown')} /></Field>
        <Field label="Fuel used (litres)" htmlFor="lb-f" hint="For the record; fuel is costed in the Fuel register"><NumField id="lb-f" value={n.fuel} onValue={num('fuel')} /></Field>
        <Field label="Work description" htmlFor="lb-w" className="sm:col-span-3"><Input id="lb-w" value={f.work_done} maxLength={300} onChange={set('work_done')} /></Field>
        <Field label="Supervisor remarks" htmlFor="lb-r" className="sm:col-span-3"><Input id="lb-r" value={f.supervisor_remarks} onChange={set('supervisor_remarks')} /></Field>
        {l && <Field label="Reason for the correction" htmlFor="lb-why" error={tried ? errors.why : ''} className="sm:col-span-3"><Input id="lb-why" value={f.correction_reason} onChange={set('correction_reason')} /></Field>}
      </div>
      {duty != null && <p className="mt-3 rounded-lg bg-muted px-3 py-2 text-[13px]">On duty <strong>{Math.round(duty * 100) / 100} h</strong> - machine running <strong>{Math.round(running * 100) / 100} h</strong>, idle about {Math.max(0, Math.round((duty - running - n.breakdown) * 100) / 100)} h. Overtime is what passes the company's regular hours.</p>}
      <FormFoot error={save.error?.message} busy={save.isPending} label={l ? 'Save the correction' : 'Log the shift'} onClose={onClose} onSave={() => (bad ? setTried(true) : save.mutate())} />
    </div>
  )
}
