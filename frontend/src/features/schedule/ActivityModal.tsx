import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { saveActivity, schKeys, useWorkOrderLines, useWorkOrdersOf, type Activity, type Employee } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'
import { MasterDeleteDialog } from '@/features/deleteorder/MasterDelete'
import { useSession } from '@/lib/session'

const STATUSES = ['Not Started', 'In Progress', 'Completed', 'Delayed'] as const

export function ActivityModal({ job, activity, others, employees = [], teamScope = 'project', milestone = false, open, onClose }: { job: number; activity: Activity | null; others: Activity[]; employees?: Employee[]; teamScope?: string; milestone?: boolean; open: boolean; onClose: () => void }) {
  const isMilestone = activity ? activity.is_milestone : milestone
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={activity ? `Edit ${activity.code || activity.name}` : milestone ? 'New milestone' : 'New activity'} description={isMilestone ? 'A point in time that marks a stage of the project: one date, and who is answerable for it.' : 'An activity tied to a work order line fills its progress itself from the measurement book.'}>
      {open && <Form key={activity?.id ?? 'new'} job={job} activity={activity} others={others} employees={employees} teamScope={teamScope} milestone={milestone} onClose={onClose} />}
    </Modal>
  )
}

/** The chain of activities an activity waits on, nearest first - to see whether choosing one would make a loop. */
const chainOf = (start: number | null | undefined, all: Activity[]) => {
  const seen: number[] = []
  let cur = start ?? null
  while (cur != null && !seen.includes(cur)) {
    seen.push(cur)
    cur = all.find((x) => x.id === cur)?.depends_on_id ?? null
  }
  return seen
}

function Form({ job, activity, others, employees, teamScope, milestone: asMilestone, onClose }: { job: number; activity: Activity | null; others: Activity[]; employees: Employee[]; teamScope: string; milestone: boolean; onClose: () => void }) {
  const orders = useWorkOrdersOf(job)
  const lines = useWorkOrderLines(orders.data ?? [])
  const [name, setName] = useState(activity?.name ?? '')
  const [code, setCode] = useState(activity?.code ?? '')
  const [start, setStart] = useState(activity?.planned_start ?? today())
  const [finish, setFinish] = useState(activity?.planned_finish ?? '')
  const [weight, setWeight] = useState(activity?.weight ?? 0)
  const [after, setAfter] = useState(activity?.depends_on_id ? String(activity.depends_on_id) : '')
  const [line, setLine] = useState(activity?.work_order_line_id ? String(activity.work_order_line_id) : '')
  const [milestone, setMilestone] = useState(activity ? !!activity.is_milestone : asMilestone)
  const [who, setWho] = useState(activity?.assigned_to_id ? String(activity.assigned_to_id) : '')
  // Shows the status as it stands. Saved as chosen only if it is changed here; left alone, a status that was only worked out stays worked out.
  const [status, setStatus] = useState<string>(activity?.status || 'Not Started')
  const [statusTouched, setStatusTouched] = useState(false)
  const [notes, setNotes] = useState(activity?.notes ?? '')
  const [tried, setTried] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const { isOwner } = useSession()

  const pred = after ? others.find((x) => x.id === Number(after)) : undefined
  const loops = !!activity && !!after && chainOf(Number(after), others).includes(activity.id)
  const clash = code.trim() ? others.find((x) => x.id !== activity?.id && (x.code || '').trim().toLowerCase() === code.trim().toLowerCase()) : undefined
  const end = milestone ? start : finish
  const errors = {
    name: name.trim() ? '' : milestone ? 'What is the milestone?' : 'What is the activity?',
    code: clash ? `${clash.code} is already used by "${clash.name}" - codes are not repeated.` : '',
    start: !start ? (milestone ? 'Give the date.' : 'Give the start date.') : '',
    finish: milestone ? '' : !finish ? 'Give the end date.' : finish < start ? 'It cannot end before it starts.' : '',
    after: loops ? 'That would make the activities wait on each other for ever.' : '',
    line: status === 'Completed' && line ? 'Its progress comes from the measurement book, so it cannot be marked completed by hand.' : '',
  }
  const bad = Object.values(errors).some(Boolean)
  // Not an error - the forecast pushes it later - but worth saying before it is saved.
  const early = pred && start && pred.planned_finish && start <= pred.planned_finish ? `It starts before ${pred.code || pred.name} finishes (${formatDate(pred.planned_finish)}); it will be forecast from that date.` : ''

  const refresh = { invalidate: [schKeys.all] }
  const save = useAction(() => saveActivity(job, activity?.id ?? null, { name, code, planned_start: start, planned_finish: end, weight, depends_on_id: after ? Number(after) : null, work_order_line_id: line ? Number(line) : null, is_milestone: milestone, assigned_to_id: who ? Number(who) : null, status: statusTouched ? status : (activity?.stored_status ?? ''), notes }), { ...refresh, success: milestone ? 'Milestone saved' : 'Activity saved', onSuccess: onClose })
  return (
    <div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field label={milestone ? 'Milestone' : 'Activity'} htmlFor="ac-name" error={tried ? errors.name : ''} className="sm:col-span-2"><Input id="ac-name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
        <Field label="Code" htmlFor="ac-code" error={errors.code} hint={code ? undefined : 'Left blank, one is given'}><Input id="ac-code" value={code} maxLength={30} aria-invalid={!!errors.code || undefined} onChange={(e) => setCode(e.target.value)} /></Field>
        <Field label={milestone ? 'Date due' : 'Starts'} htmlFor="ac-start" error={tried ? errors.start : ''}><Input id="ac-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        {!milestone && <Field label="Ends" htmlFor="ac-finish" error={tried ? errors.finish : errors.finish && finish ? errors.finish : ''}><Input id="ac-finish" type="date" min={start || undefined} value={finish} onChange={(e) => setFinish(e.target.value)} /></Field>}
        <Field label="Status" htmlFor="ac-status" error={errors.line}><Select id="ac-status" value={status} onChange={(e) => { setStatus(e.target.value); setStatusTouched(true) }} options={STATUSES.map((s) => ({ value: s, label: s }))} /></Field>
        <Field label="Assigned to" htmlFor="ac-who" className="sm:col-span-3" hint={teamScope === 'company' ? 'Nobody is placed on this project yet, so everyone in the company is listed.' : 'The people on this project.'}><Select id="ac-who" value={who} placeholder="Nobody yet" onChange={(e) => setWho(e.target.value)} options={employees.map((x) => ({ value: x.id, label: x.name }))} /></Field>
        {!milestone && <Field label="Weight" htmlFor="ac-weight" hint="Its share of the whole"><NumField id="ac-weight" value={weight} onValue={setWeight} /></Field>}
        <Field label={milestone ? 'Reached after' : 'Cannot start until'} htmlFor="ac-after" error={errors.after} hint={errors.after ? undefined : early} className="sm:col-span-3"><Select id="ac-after" value={after} placeholder={milestone ? 'Nothing - it stands on its own date' : 'Nothing - it can start on its date'} onChange={(e) => setAfter(e.target.value)} options={others.filter((x) => x.id !== activity?.id).map((x) => ({ value: x.id, label: `${x.code} ${x.name}`, disabled: !!activity && chainOf(x.id, others).includes(activity.id) }))} /></Field>
        {!milestone && <Field label="Progress comes from" htmlFor="ac-line" className="sm:col-span-3"><Select id="ac-line" value={line} placeholder="Reported by hand" onChange={(e) => setLine(e.target.value)} options={(lines.data ?? []).map((l) => ({ value: l.id, label: l.label }))} /></Field>}
        <Field label="Description / notes" htmlFor="ac-notes" hint="Optional" className="sm:col-span-3"><Textarea id="ac-notes" rows={3} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        <label className="flex items-center gap-2 text-sm sm:col-span-3"><input type="checkbox" checked={milestone} onChange={(e) => setMilestone(e.target.checked)} /> A milestone (a point in time, not a stretch of work)</label>
      </div>
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {activity && isOwner && <Button variant="danger" className="mr-auto" onClick={() => setDeleting(true)}>Delete this {milestone ? 'milestone' : 'activity'}</Button>}
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => (bad ? setTried(true) : save.mutate())}>{milestone ? 'Save the milestone' : 'Save the activity'}</Button>
      </div>
      {activity && <MasterDeleteDialog simple open={deleting} onOpenChange={setDeleting} kind="activity" id={activity.id} label={activity.code || activity.name} noun={milestone ? 'milestone' : 'activity'} onDeleted={onClose} />}
    </div>
  )
}
