import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { reportIncident, safetyKeys } from '@/api/safety'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'

export function IncidentModal({ job, kinds, open, onClose }: { job: number; kinds: string[]; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Report an incident" description="A near miss written down is the cheapest lesson there is.">
      {open && <Form job={job} kinds={kinds} onClose={onClose} />}
    </Modal>
  )
}

function Form({ job, kinds, onClose }: { job: number; kinds: string[]; onClose: () => void }) {
  const [f, setF] = useState({ kind: kinds[0] ?? '', happened_on: today(), happened_at: '', location: '', description: '', injured_name: '', injury: '', treatment: '', lost_days: 0, immediate_action: '' })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const save = useAction(() => reportIncident({ job_id: job, ...f }), { invalidate: [safetyKeys.all, ['staff']], success: (r) => `${r.incident.number} reported`, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="What kind" htmlFor="si-kind"><Select id="si-kind" value={f.kind} onChange={set('kind')} options={kinds.map((k) => ({ value: k, label: k }))} /></Field>
        <Field label="On" htmlFor="si-date"><Input id="si-date" type="date" value={f.happened_on} onChange={set('happened_on')} /></Field>
        <Field label="At" htmlFor="si-time"><Input id="si-time" type="time" value={f.happened_at} onChange={set('happened_at')} /></Field>
        <Field label="Where" htmlFor="si-where" className="sm:col-span-3"><Input id="si-where" value={f.location} placeholder="Tower A, level 3" onChange={set('location')} /></Field>
        <Field label="What happened" htmlFor="si-what" className="sm:col-span-3"><Textarea id="si-what" rows={3} value={f.description} onChange={set('description')} /></Field>
        <Field label="Who was hurt" htmlFor="si-who"><Input id="si-who" value={f.injured_name} onChange={set('injured_name')} /></Field>
        <Field label="Injury" htmlFor="si-injury"><Input id="si-injury" value={f.injury} onChange={set('injury')} /></Field>
        <Field label="Days lost" htmlFor="si-lost"><NumField id="si-lost" value={f.lost_days} onValue={(n) => setF((x) => ({ ...x, lost_days: n }))} /></Field>
        <Field label="Treatment" htmlFor="si-treat" className="sm:col-span-3"><Input id="si-treat" value={f.treatment} placeholder="First aid on site, hospital..." onChange={set('treatment')} /></Field>
        <Field label="What was done straight away" htmlFor="si-action" className="sm:col-span-3"><Input id="si-action" value={f.immediate_action} onChange={set('immediate_action')} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!f.description.trim()} onClick={() => save.mutate()}>Report it</Button>
      </div>
    </div>
  )
}
