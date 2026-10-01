import { useState } from 'react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { issuePermit, safetyKeys } from '@/api/safety'
import { useAction } from '@/lib/mutate'

const dt = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`

export function PermitModal({ job, kinds, open, onClose }: { job: number; kinds: Record<string, string[]>; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Permit to work" description="Issued by a supervisor for one shift at most, once the precautions are in place.">
      {open && <Form job={job} kinds={kinds} onClose={onClose} />}
    </Modal>
  )
}

function Form({ job, kinds, onClose }: { job: number; kinds: Record<string, string[]>; onClose: () => void }) {
  const names = Object.keys(kinds)
  const [kind, setKind] = useState(names[0] ?? '')
  const [where, setWhere] = useState('')
  const [what, setWhat] = useState('')
  const [who, setWho] = useState('')
  const [from, setFrom] = useState(dt(new Date()))
  const [to, setTo] = useState(dt(new Date(Date.now() + 8 * 3600_000)))
  const [done, setDone] = useState<Record<string, boolean>>({})
  const items = kinds[kind] ?? []
  const save = useAction(() => issuePermit({ job_id: job, kind, location: where, description: what, receiver: who, valid_from: from, valid_to: to, precautions: items.map((item) => ({ item, done: !!done[item] })) }), { invalidate: [safetyKeys.all, ['staff']], success: (r) => `${r.permit.number} issued, until ${r.permit.valid_to}`, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="For" htmlFor="sp-kind"><Select id="sp-kind" value={kind} onChange={(e) => { setKind(e.target.value); setDone({}) }} options={names.map((k) => ({ value: k, label: k }))} /></Field>
        <Field label="Where" htmlFor="sp-where"><Input id="sp-where" value={where} onChange={(e) => setWhere(e.target.value)} /></Field>
        <Field label="The work" htmlFor="sp-what" className="sm:col-span-2"><Input id="sp-what" value={what} onChange={(e) => setWhat(e.target.value)} /></Field>
        <Field label="From" htmlFor="sp-from"><Input id="sp-from" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="Until (one shift at most)" htmlFor="sp-to"><Input id="sp-to" type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        <Field label="Who does the work" htmlFor="sp-who" className="sm:col-span-2"><Input id="sp-who" value={who} onChange={(e) => setWho(e.target.value)} /></Field>
      </div>
      <fieldset className="mt-4 rounded-lg border border-border p-3">
        <legend className="px-1 text-[13px] font-semibold">In place before it is issued</legend>
        {items.map((item) => <label key={item} className="my-1 flex items-center gap-2 text-sm"><input type="checkbox" checked={!!done[item]} onChange={(e) => setDone((d) => ({ ...d, [item]: e.target.checked }))} /> {item}</label>)}
      </fieldset>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!who.trim()} onClick={() => save.mutate()}>Issue the permit</Button>
      </div>
    </div>
  )
}
