import { useRef, useState } from 'react'
import { Button, Field, Input, Modal, Select, Textarea } from '@/components/ui'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { qcKeys, registerInspection, useTemplates, type CheckItem, type Inspection } from '@/api/quality'
import { uploadFiles } from '@/api/files'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { today } from '@/lib/format'
import { toast } from '@/stores/toast'
import { FilePick } from './parts'

type Outcome = '' | 'Pass' | 'Fail'

/** Put an inspection that has been carried out on the record: what, where, who, what each check found, how it came out. */
export function RegisterInspectionModal({ job, open, onClose, onRegistered }: { job: number; open: boolean; onClose: () => void; onRegistered: (i: Inspection) => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Register an inspection" description="Record an inspection that has been carried out: what was checked, what was found, and how it came out." size="xl">
      {open && <Form job={job} onClose={onClose} onRegistered={onRegistered} />}
    </Modal>
  )
}

function Form({ job: initial, onClose, onRegistered }: { job: number; onClose: () => void; onRegistered: (i: Inspection) => void }) {
  const { user, can } = useSession()
  const [job, setJob] = useState(initial)
  const templates = useTemplates(job)
  const [f, setF] = useState({ work_activity: '', inspector: user?.name ?? '', location: '', building: '', floor_area: '', witnessed_by: '', defects: '' })
  const [on, setOn] = useState(today())
  const [list, setList] = useState('')
  const [edited, setEdited] = useState<CheckItem[] | null>(null)
  const [outcome, setOutcome] = useState<Outcome>('')
  const [status, setStatus] = useState('Pending')
  const [files, setFiles] = useState<File[]>([])
  const [tried, setTried] = useState(false)
  // A second click in the same instant would start a second save before the screen has drawn the first one as busy.
  const sending = useRef(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const all = templates.data ?? []
  const name = list || all[0]?.name || ''
  const base = (all.find((t) => t.name === name)?.items ?? []).map((x) => ({ item: x.item, criteria: x.criteria, result: '', remark: '' }))
  const items: CheckItem[] = edited ?? base
  const setItem = (n: number, patch: Partial<CheckItem>) => setEdited(items.map((x, i) => (i === n ? { ...x, ...patch } : x)))
  const canFinal = can('site.signoff')

  // What may be chosen as the status follows the result: a final one only by whoever signs off.
  const statuses = outcome === '' ? ['Pending'] : [...(canFinal ? [outcome === 'Pass' ? 'Passed' : 'Failed'] : []), 'Awaiting Approval']
  const effective = statuses.includes(status) ? status : statuses[0]
  const pick = (o: Outcome) => {
    setOutcome(o)
    if (o === 'Pass') setEdited(items.map((x) => (x.result ? x : { ...x, result: 'ok' })))
    setStatus(o === '' ? 'Pending' : canFinal ? (o === 'Pass' ? 'Passed' : 'Failed') : 'Awaiting Approval')
  }

  const unlooked = items.filter((x) => !x.result).length
  const notOk = items.filter((x) => x.result === 'not ok').length
  const errors = {
    job: job ? '' : 'Choose the project.',
    work_activity: f.work_activity.trim() ? '' : 'Which activity or work item was inspected?',
    inspector: f.inspector.trim() ? '' : 'Who carried out the inspection?',
    on: !on ? 'Give the inspection date.' : on > today() ? 'An inspection cannot be dated in the future.' : '',
    checklist: name ? '' : 'Choose a checklist.',
    result: outcome && unlooked ? `${unlooked} check${unlooked === 1 ? '' : 's'} not looked at yet.` : outcome === 'Pass' && notOk ? 'It cannot pass with a check marked not ok.' : outcome === 'Fail' && !notOk && !f.defects.trim() ? 'Mark the check that failed, or describe the defect.' : '',
  }
  const bad = Object.values(errors).some(Boolean)

  const save = useAction(
    async () => {
      try {
      const r = await registerInspection({ job_id: job, ...f, checklist: name, inspected_on: on, items, result: outcome, status: effective })
      const up = files.length ? await uploadFiles(files, 'inspection', r.inspection.id) : { done: 0, failed: [] as string[] }
      return { ...r, failed: up.failed }
      } finally {
        sending.current = false
      }
    },
    {
      invalidate: [qcKeys.all],
      // Said only once the server has answered with the saved record.
      success: (r) => `${r.inspection.number} registered - ${r.inspection.result_label.toLowerCase()}${r.inspection.approval_status === 'submitted' ? ', awaiting approval' : ''}`,
      onSuccess: (r) => { if (r.failed.length) toast.error(`The inspection was saved, but not every file: ${r.failed.join(' - ')}`); onRegistered(r.inspection) },
    },
  )
  return (
    <div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Project" htmlFor="rg-job" error={tried ? errors.job : ''}><ProjectPicker id="rg-job" value={job} onChange={(j) => { setJob(j); setEdited(null); setList('') }} className="w-full" /></Field>
        <Field label="Activity or work item" htmlFor="rg-act" error={tried ? errors.work_activity : ''}><Input id="rg-act" value={f.work_activity} maxLength={200} placeholder="Slab reinforcement, internal plaster..." onChange={set('work_activity')} /></Field>
        <Field label="Inspection date" htmlFor="rg-date" error={tried ? errors.on : ''}><Input id="rg-date" type="date" max={today()} value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Inspector name" htmlFor="rg-by" error={tried ? errors.inspector : ''}><Input id="rg-by" value={f.inspector} maxLength={120} onChange={set('inspector')} /></Field>
        <Field label="Location" htmlFor="rg-where"><Input id="rg-where" value={f.location} placeholder="Block A, 2nd floor, grid C-D" onChange={set('location')} /></Field>
        <Field label="Witnessed by" htmlFor="rg-wit"><Input id="rg-wit" value={f.witnessed_by} placeholder="Client's engineer" onChange={set('witnessed_by')} /></Field>
        <Field label="Quality checklist" htmlFor="rg-list" error={tried ? errors.checklist : ''} className="sm:col-span-2"><Select id="rg-list" value={name} onChange={(e) => { setList(e.target.value); setEdited(null) }} options={all.map((t) => ({ value: t.name, label: t.work_type ? `${t.name} - ${t.work_type}` : t.name }))} /></Field>
      </div>

      <div className="mt-4 overflow-x-auto rounded-lg border border-border">
        <table aria-label="Inspection criteria" className="w-full min-w-[34rem] text-[13.5px]">
          <thead className="bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Check and what it must meet</th><th className="px-2 text-center">OK</th><th className="px-2 text-center">Not OK</th><th className="px-2 text-center">N/A</th><th className="px-3">Remark</th></tr></thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={5} className="p-4 text-center text-muted-foreground">{templates.isPending ? 'Loading the checklist...' : 'Choose a project and a checklist.'}</td></tr>}
            {items.map((x, n) => (
              <tr key={`${name}-${n}`} className="border-t border-border align-top">
                <td className="px-3 py-2">{x.item}{x.criteria && <div className="text-xs text-muted-foreground">Must meet: {x.criteria}</div>}</td>
                {(['ok', 'not ok', 'na'] as const).map((v) => <td key={v} className="px-2 py-2 text-center"><input type="radio" aria-label={`${x.item}: ${v}`} name={`rg-${n}`} checked={x.result === v} onChange={() => setItem(n, { result: v })} /></td>)}
                <td className="px-3 py-1.5"><Input aria-label={`Remark for ${x.item}`} className="min-w-32" value={x.remark ?? ''} onChange={(e) => setItem(n, { remark: e.target.value })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <fieldset>
          <legend className="mb-1.5 text-[13px] font-medium">Inspection result</legend>
          <div role="radiogroup" aria-label="Inspection result" className="flex flex-wrap gap-3 text-sm">
            {([['', 'Not decided yet'], ['Pass', 'Pass'], ['Fail', 'Fail']] as const).map(([v, l]) => <label key={v} className="flex items-center gap-1.5"><input type="radio" name="rg-result" checked={outcome === v} onChange={() => pick(v)} /> {l}</label>)}
          </div>
          {tried && errors.result && <p role="alert" className="mt-1 text-xs text-danger">{errors.result}</p>}
        </fieldset>
        <Field label="Status" htmlFor="rg-status" hint={canFinal ? undefined : 'A final Passed or Failed is recorded by whoever signs off site work; yours goes to them for approval.'}><Select id="rg-status" value={effective} onChange={(e) => setStatus(e.target.value)} options={statuses.map((s) => ({ value: s, label: s }))} /></Field>
        <Field label="Remarks or defects found" htmlFor="rg-def" className="sm:col-span-2" hint={outcome === 'Fail' ? 'Describe what was found - it goes on the record and on any non-conformance raised from it.' : undefined}><Textarea id="rg-def" rows={3} maxLength={2000} value={f.defects} onChange={set('defects')} /></Field>
        <div className="sm:col-span-2"><FilePick files={files} onChange={setFiles} label="Attach photos or documents" /></div>
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={save.isPending} onClick={() => { if (bad) return setTried(true); if (sending.current) return; sending.current = true; save.mutate() }}>Register inspection</Button>
      </div>
    </div>
  )
}
