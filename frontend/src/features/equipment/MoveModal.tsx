import { useState } from 'react'
import { Field, Input, Modal, Select } from '@/components/ui'
import { eqKeys, moveMachine, type Machine } from '@/api/equipment'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { Footer } from './Footer'

/** Send a machine to a site, or back to the yard. */
export function MoveModal({ machine, onClose }: { machine: Machine | null; onClose: () => void }) {
  return (
    <Modal open={!!machine} onOpenChange={(o) => !o && onClose()} title={machine ? `${machine.current_job_id ? 'Move' : 'Deploy'} ${machine.code} ${machine.name}` : ''}>
      {machine && <MoveForm key={machine.id} machine={machine} onClose={onClose} />}
    </Modal>
  )
}

function MoveForm({ machine, onClose }: { machine: Machine; onClose: () => void }) {
  const jobs = useProjects()
  const [to, setTo] = useState('')
  const [on, setOn] = useState(today())
  const [note, setNote] = useState('')
  const save = useAction(() => moveMachine(machine.id, { to_job_id: to ? Number(to) : null, moved_on: on, note }), { invalidate: [eqKeys.all], success: (r) => r.message, onSuccess: onClose })
  const options = (jobs.data ?? []).filter((j) => j.id !== machine.current_job_id && !['complete', 'cancelled'].includes(j.status)).map((j) => ({ value: j.id, label: projectLabel(j) }))
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="To" htmlFor="mv-to" className="sm:col-span-2"><Select id="mv-to" value={to} placeholder={machine.current_job_id ? 'Back to the yard' : 'Choose a site'} onChange={(e) => setTo(e.target.value)} options={options} /></Field>
        <Field label="On" htmlFor="mv-on"><Input id="mv-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Note" htmlFor="mv-note"><Input id="mv-note" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <Footer error={save.error?.message} busy={save.isPending} label={machine.current_job_id ? 'Move it' : 'Deploy it'} disabled={!machine.current_job_id && !to} onClose={onClose} onSave={() => save.mutate()} />
    </div>
  )
}
