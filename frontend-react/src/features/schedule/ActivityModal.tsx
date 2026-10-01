import { useState } from 'react'
import { Button, ConfirmDialog, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { deleteActivity, saveActivity, schKeys, useWorkOrderLines, useWorkOrdersOf, type Activity } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'

export function ActivityModal({ job, activity, others, open, onClose }: { job: number; activity: Activity | null; others: Activity[]; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={activity ? `Edit ${activity.code || activity.name}` : 'New activity'} description="An activity tied to a work order line fills its progress itself from the measurement book.">
      {open && <Form key={activity?.id ?? 'new'} job={job} activity={activity} others={others} onClose={onClose} />}
    </Modal>
  )
}

function Form({ job, activity, others, onClose }: { job: number; activity: Activity | null; others: Activity[]; onClose: () => void }) {
  const orders = useWorkOrdersOf(job)
  const lines = useWorkOrderLines(orders.data ?? [])
  const [name, setName] = useState(activity?.name ?? '')
  const [code, setCode] = useState(activity?.code ?? '')
  const [start, setStart] = useState(activity?.planned_start ?? today())
  const [finish, setFinish] = useState(activity?.planned_finish ?? '')
  const [weight, setWeight] = useState(activity?.weight ?? 0)
  const [after, setAfter] = useState(activity?.depends_on_id ? String(activity.depends_on_id) : '')
  const [line, setLine] = useState(activity?.work_order_line_id ? String(activity.work_order_line_id) : '')
  const [milestone, setMilestone] = useState(!!activity?.is_milestone)
  const [removing, setRemoving] = useState(false)
  const refresh = { invalidate: [schKeys.all] }
  const save = useAction(() => saveActivity(job, activity?.id ?? null, { name, code, planned_start: start, planned_finish: finish, weight, depends_on_id: after ? Number(after) : null, work_order_line_id: line ? Number(line) : null, is_milestone: milestone }), { ...refresh, success: 'Activity saved', onSuccess: onClose })
  const remove = useAction(() => deleteActivity(activity?.id as number), { ...refresh, success: 'Activity removed', onSuccess: () => { setRemoving(false); onClose() } })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Activity" htmlFor="ac-name" className="sm:col-span-2"><Input id="ac-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
        <Field label="Code" htmlFor="ac-code"><Input id="ac-code" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
        <Field label="Starts" htmlFor="ac-start"><Input id="ac-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="Finishes" htmlFor="ac-finish"><Input id="ac-finish" type="date" value={finish} onChange={(e) => setFinish(e.target.value)} /></Field>
        <Field label="Weight" htmlFor="ac-weight" hint="Its share of the whole"><NumField id="ac-weight" value={weight} onValue={setWeight} /></Field>
        <Field label="Cannot start until" htmlFor="ac-after" className="sm:col-span-3"><Select id="ac-after" value={after} placeholder="Nothing - it can start on its date" onChange={(e) => setAfter(e.target.value)} options={others.filter((x) => x.id !== activity?.id).map((x) => ({ value: x.id, label: `${x.code} ${x.name}` }))} /></Field>
        <Field label="Progress comes from" htmlFor="ac-line" className="sm:col-span-3"><Select id="ac-line" value={line} placeholder="Reported by hand" onChange={(e) => setLine(e.target.value)} options={(lines.data ?? []).map((l) => ({ value: l.id, label: l.label }))} /></Field>
        <label className="flex items-center gap-2 text-sm sm:col-span-3"><input type="checkbox" checked={milestone} onChange={(e) => setMilestone(e.target.checked)} /> A milestone (a point in time, not a stretch of work)</label>
      </div>
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {activity && <Button variant="ghost" className="mr-auto text-danger" onClick={() => setRemoving(true)}>Remove</Button>}
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!name.trim() || !start || !finish} onClick={() => save.mutate()}>Save the activity</Button>
      </div>
      <ConfirmDialog open={removing} onOpenChange={setRemoving} title="Remove this activity?" description="Anything that followed it will follow what it followed." confirmLabel="Remove" tone="danger" loading={remove.isPending} onConfirm={() => remove.mutate()} />
    </div>
  )
}
