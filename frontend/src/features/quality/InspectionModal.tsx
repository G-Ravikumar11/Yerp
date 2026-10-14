import { useState } from 'react'
import { FileText, Image } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Select, Skeleton, Textarea } from '@/components/ui'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { closeInspection, qcKeys, reinspect, returnInspection, saveInspection, startInspection, submitInspection, useInspection, useTemplates, type Inspection } from '@/api/quality'
import { projectLabel, useProjects } from '@/api/projects'
import { uploadFiles } from '@/api/files'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { toast } from '@/stores/toast'
import { Fact, FilePick, History, Section, inspectionTone } from './parts'

/** Start an inspection: where, what work, which checklist, who inspects - and the photographs of it. */
export function NewInspectionModal({ job, open, onClose, onStarted }: { job: number; open: boolean; onClose: () => void; onStarted: (i: Inspection) => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="New inspection" description="Walk the checklist before the work is covered up." size="lg">
      {open && <NewForm job={job} onClose={onClose} onStarted={onStarted} />}
    </Modal>
  )
}

const blank = { building: '', floor_area: '', location: '', work_activity: '', checklist: '', assigned_to: '', witnessed_by: '', measurements: '', remarks: '' }

function NewForm({ job: initial, onClose, onStarted }: { job: number; onClose: () => void; onStarted: (i: Inspection) => void }) {
  const [job, setJob] = useState(initial)
  const [f, setF] = useState(blank)
  const [on, setOn] = useState(today())
  const [files, setFiles] = useState<File[]>([])
  const [tried, setTried] = useState(false)
  const projects = useProjects()
  const lists = useTemplates(job)
  const templates = lists.data ?? []
  const site = projects.data?.find((p) => p.id === job)?.site_address
  const set = (k: keyof typeof blank) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const checklist = f.checklist || templates[0]?.name || ''
  const errors = {
    job: job ? '' : 'Choose the project.',
    checklist: checklist ? '' : 'Choose a checklist.',
    on: !on ? 'Give the date.' : on > today() ? 'An inspection cannot be dated in the future.' : '',
  }
  const bad = Object.values(errors).some(Boolean)
  const start = useAction(
    async () => {
      const r = await startInspection({ job_id: job, ...f, checklist, inspected_on: on })
      let note = ''
      if (files.length) {
        const up = await uploadFiles(files, 'inspection', r.inspection.id)
        if (up.failed.length) note = up.failed.join(' - ')
      }
      return { ...r, note }
    },
    { invalidate: [qcKeys.all], success: false, onSuccess: (r) => { if (r.note) toast.error(`Started, but not every file was saved: ${r.note}`); onStarted(r.inspection) } },
  )
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Project" htmlFor="qn-job" error={tried ? errors.job : ''}><ProjectPicker id="qn-job" value={job} onChange={setJob} className="w-full" /></Field>
        <Field label="Site" htmlFor="qn-site"><Input id="qn-site" readOnly value={site || (job ? projectLabel(projects.data?.find((p) => p.id === job) ?? { id: 0, number: '', name: '', customer_name: '', status: '' }) : '')} placeholder="Taken from the project" /></Field>
        <Field label="Building / block" htmlFor="qn-bld"><Input id="qn-bld" value={f.building} placeholder="Block A" onChange={set('building')} /></Field>
        <Field label="Floor / area" htmlFor="qn-floor"><Input id="qn-floor" value={f.floor_area} placeholder="2nd floor slab" onChange={set('floor_area')} /></Field>
        <Field label="Location detail" htmlFor="qn-where"><Input id="qn-where" value={f.location} placeholder="Raft, grid A-C" onChange={set('location')} /></Field>
        <Field label="Work activity" htmlFor="qn-act"><Input id="qn-act" value={f.work_activity} placeholder="Slab reinforcement" onChange={set('work_activity')} /></Field>
        <Field label="Checklist" htmlFor="qn-list" error={tried ? errors.checklist : ''} hint="Items and what each must meet come from the checklist."><Select id="qn-list" value={checklist} onChange={set('checklist')} options={templates.map((t) => ({ value: t.name, label: t.work_type ? `${t.name} - ${t.work_type}` : t.name }))} /></Field>
        <Field label="Inspection date" htmlFor="qn-date" error={tried ? errors.on : ''}><Input id="qn-date" type="date" max={today()} value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Assigned inspector" htmlFor="qn-by"><Input id="qn-by" value={f.assigned_to} placeholder="Who is to inspect" onChange={set('assigned_to')} /></Field>
        <Field label="Witnessed by" htmlFor="qn-witness"><Input id="qn-witness" value={f.witnessed_by} placeholder="Client's engineer" onChange={set('witnessed_by')} /></Field>
        <Field label="Measurements" htmlFor="qn-meas" className="sm:col-span-2" hint="What was measured on site - cover, spacing, thickness. Each check can also carry its own reading."><Textarea id="qn-meas" rows={2} value={f.measurements} onChange={set('measurements')} /></Field>
        <Field label="Remarks" htmlFor="qn-rem" className="sm:col-span-2"><Textarea id="qn-rem" rows={2} value={f.remarks} onChange={set('remarks')} /></Field>
        <div className="sm:col-span-2"><FilePick files={files} onChange={setFiles} label="Attach photos" /></div>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {start.error && <p role="alert" className="mr-auto text-[13px] text-danger">{start.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={start.isPending} disabled={start.isPending} onClick={() => (bad ? setTried(true) : start.mutate())}>Start it</Button>
      </div>
    </div>
  )
}

/** One inspection: its checks, what was measured, the decision it is waiting on, and its trail. */
export function InspectionModal({ id, onClose, onPhotos, onNcr, onOpen }: { id: number | null; onClose: () => void; onPhotos: (i: Inspection) => void; onNcr: (i: Inspection) => void; onOpen: (id: number) => void }) {
  const q = useInspection(id)
  const i = q.data?.inspection
  return (
    <Modal open={!!id} onOpenChange={(o) => !o && onClose()} title={i ? `${i.number} - ${i.checklist}${i.location ? ` - ${i.location}` : ''}` : 'Inspection'} size="xl">
      {q.isPending && <Skeleton className="h-48 w-full" />}
      {q.isError && <p role="alert" className="text-[13px] text-danger">{q.error.message}</p>}
      {i && <Walk key={`${i.id}-${i.result}-${i.approval_status}`} inspection={i} history={q.data?.history} onClose={onClose} onPhotos={onPhotos} onNcr={onNcr} onOpen={onOpen} />}
    </Modal>
  )
}

function Walk({ inspection: i, history, onClose, onPhotos, onNcr, onOpen }: { inspection: Inspection; history?: import('@/api/quality').HistoryLine[]; onClose: () => void; onPhotos: (i: Inspection) => void; onNcr: (i: Inspection) => void; onOpen: (id: number) => void }) {
  const { can } = useSession()
  const [items, setItems] = useState(() => i.items.map((x) => ({ ...x })))
  const [measurements, setMeasurements] = useState(i.measurements)
  const [remarks, setRemarks] = useState(i.remarks)
  const [confirm, setConfirm] = useState<'submit' | 'approve' | 'return' | 'reinspect' | null>(null)
  const editable = i.editable && can('site.record')
  const undone = items.filter((x) => !x.result).length
  const edit = (n: number, patch: Partial<(typeof items)[number]>) => setItems((l) => l.map((x, k) => (k === n ? { ...x, ...patch } : x)))
  const refresh = [qcKeys.all]
  const save = useAction(() => saveInspection({ id: i.id, job_id: i.job_id, items, measurements, remarks }), { invalidate: refresh, success: 'Saved' })
  const submit = useAction(() => saveInspection({ id: i.id, job_id: i.job_id, items, measurements, remarks }).then(() => submitInspection(i.id)), { invalidate: refresh, success: (r) => `${r.inspection.number} is with the approver`, onSuccess: () => setConfirm(null), onError: () => setConfirm(null) })
  const approve = useAction(() => saveInspection({ id: i.id, job_id: i.job_id, items, measurements, remarks }).then(() => closeInspection(i.id)), { invalidate: refresh, success: (r) => `${r.inspection.number} ${r.inspection.result_label.toLowerCase()}`, onSuccess: () => setConfirm(null), onError: () => setConfirm(null) })
  const back = useAction((note: string) => returnInspection(i.id, note), { invalidate: refresh, success: 'Returned to the inspector', onSuccess: () => setConfirm(null) })
  const again = useAction(() => reinspect(i.id), { invalidate: refresh, success: (r) => `${r.inspection.number} opened for the reinspection`, onSuccess: (r) => { setConfirm(null); onOpen(r.inspection.id) }, onError: () => setConfirm(null) })
  const failing = items.some((x) => x.result === 'not ok')
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={inspectionTone(i.result)} dot>{i.result_label}</Badge>
        {i.approval_status === 'submitted' && <Badge tone="info" dot>Waiting for approval</Badge>}
        {i.approval_status === 'returned' && <Badge tone="warning" dot>Returned to the inspector</Badge>}
        {i.failed_items > 0 && <span className="text-xs text-danger">{i.failed_items} not ok</span>}
        {i.reinspection_of_number && <span className="text-xs text-muted-foreground">Reinspection of {i.reinspection_of_number}</span>}
      </div>
      {i.approval_status === 'returned' && i.return_note && <p role="status" className="rounded-lg border border-warning/30 bg-warning-soft p-3 text-[13px] text-warning">Returned: {i.return_note}</p>}
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact label="Project">{i.project}</Fact>
        <Fact label="Site">{i.site}</Fact>
        <Fact label="Building / floor">{[i.building, i.floor_area].filter(Boolean).join(' - ')}</Fact>
        <Fact label="Work activity">{i.work_activity}</Fact>
        <Fact label="Inspection date">{formatDate(i.inspected_on)}</Fact>
        <Fact label="Inspector">{i.assigned_to || i.inspected_by}</Fact>
        <Fact label="Recorded by">{i.inspected_by}</Fact>
        <Fact label="Witnessed by">{i.witnessed_by}</Fact>
      </dl>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table aria-label="Checks" className="w-full text-[13.5px]">
          <thead className="bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Check</th><th className="px-2 py-2 text-center">OK</th><th className="px-2 py-2 text-center">Not OK</th><th className="px-2 py-2 text-center">N/A</th><th className="px-3 py-2">Measured</th><th className="px-3 py-2">Remark</th></tr></thead>
          <tbody>
            {items.map((x, n) => (
              <tr key={n} className="border-t border-border align-top">
                <td className="px-3 py-2">{x.item}{x.criteria && <div className="text-xs text-muted-foreground">Must meet: {x.criteria}</div>}</td>
                {(['ok', 'not ok', 'na'] as const).map((v) => <td key={v} className="px-2 py-2 text-center"><input type="radio" aria-label={`${x.item}: ${v}`} name={`qc-${n}`} checked={x.result === v} disabled={!editable} onChange={() => edit(n, { result: v })} /></td>)}
                <td className="px-3 py-2"><Input aria-label={`Measured for ${x.item}`} className="min-w-24" value={x.measured ?? ''} disabled={!editable} onChange={(e) => edit(n, { measured: e.target.value })} /></td>
                <td className="px-3 py-2"><Input aria-label={`Remark for ${x.item}`} className="min-w-32" value={x.remark ?? ''} disabled={!editable} onChange={(e) => edit(n, { remark: e.target.value })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Measurements" htmlFor="qi-meas"><Textarea id="qi-meas" rows={2} value={measurements} disabled={!editable} onChange={(e) => setMeasurements(e.target.value)} /></Field>
        <Field label="Remarks" htmlFor="qi-rem"><Textarea id="qi-rem" rows={2} value={remarks} disabled={!editable} onChange={(e) => setRemarks(e.target.value)} /></Field>
      </div>
      {(i.ncrs?.length ?? 0) > 0 && <p className="text-[13px]">Non-conformance: {i.ncrs!.map((n) => n.number).join(', ')}</p>}
      {i.reinspection_number && <p className="text-[13px]">Reinspection {i.reinspection_number} - {(i.reinspection_result === 'OPEN' ? 'pending' : (i.reinspection_result ?? '').toLowerCase())}</p>}
      {i.approved_by && <p className="text-[13px] text-muted-foreground">Decided by {i.approved_by} on {formatDate(i.approved_on)}.</p>}
      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {(save.error || submit.error || approve.error || again.error) && <p role="alert" className="mr-auto text-[13px] text-danger">{(save.error ?? submit.error ?? approve.error ?? again.error)!.message}</p>}
        {i.result === 'FAILED' && can('site.record') && !i.ncrs?.length && <Button variant="outline" className="text-danger" onClick={() => onNcr(i)}>Raise NCR</Button>}
        {i.result === 'FAILED' && can('site.record') && <Button variant="outline" onClick={() => setConfirm('reinspect')}>Request reinspection</Button>}
        <Button variant="outline" onClick={() => onPhotos(i)}><Image /> Photos</Button>
        <Button variant="outline" asChild><a href={`/api/qc/inspections/${i.id}/document.pdf`} target="_blank" rel="noopener"><FileText /> PDF</a></Button>
        {editable && <Button variant="outline" loading={save.isPending} onClick={() => save.mutate()}>Save</Button>}
        {editable && <Button variant={can('site.signoff') ? 'outline' : 'primary'} disabled={undone > 0} title={undone ? `${undone} check${undone === 1 ? '' : 's'} not looked at yet` : undefined} onClick={() => setConfirm('submit')}>Submit for approval</Button>}
        {i.result === 'OPEN' && i.approval_status === 'submitted' && can('site.signoff') && <Button variant="outline" onClick={() => setConfirm('return')}>Return</Button>}
        {i.result === 'OPEN' && can('site.signoff') && <Button disabled={undone > 0} title={undone ? `${undone} check${undone === 1 ? '' : 's'} not looked at yet` : undefined} onClick={() => setConfirm('approve')}>Approve</Button>}
        {i.result !== 'OPEN' && <Button onClick={onClose}>Done</Button>}
      </div>
      <Section title="History"><History lines={history} /></Section>

      <ConfirmDialog open={confirm === 'submit'} onOpenChange={(o) => !o && setConfirm(null)} title={`Submit ${i.number} for approval?`} description={`It is locked while it waits. ${failing ? 'Some checks are marked not ok.' : 'Every check is marked ok or not applicable.'}`} confirmLabel="Submit" loading={submit.isPending} onConfirm={() => submit.mutate()} />
      <ConfirmDialog open={confirm === 'approve'} onOpenChange={(o) => !o && setConfirm(null)} title={`Approve ${i.number} as ${failing ? 'FAILED' : 'passed'}?`} description={failing ? 'A check is marked not ok, so the inspection fails and corrective action follows. This cannot be undone - a failed inspection is re-inspected, not edited.' : 'Every check is ok, so it passes. This cannot be undone.'} tone={failing ? 'danger' : 'primary'} confirmLabel={failing ? 'Fail it' : 'Pass it'} loading={approve.isPending} onConfirm={() => approve.mutate()} />
      <ConfirmDialog open={confirm === 'return'} onOpenChange={(o) => !o && setConfirm(null)} title={`Return ${i.number} to the inspector?`} reason={{ label: 'What is to be looked at again', required: true }} confirmLabel="Return it" loading={back.isPending} onConfirm={(note) => back.mutate(note)} />
      <ConfirmDialog open={confirm === 'reinspect'} onOpenChange={(o) => !o && setConfirm(null)} title={`Request a reinspection of ${i.number}?`} description="Open a fresh checklist for the same place, once the corrective work is done. This inspection stays on record as failed." confirmLabel="Open reinspection" loading={again.isPending} onConfirm={() => again.mutate()} />
    </div>
  )
}
