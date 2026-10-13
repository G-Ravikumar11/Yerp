import { useState } from 'react'
import { FileText, Image } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Select, Skeleton, Textarea } from '@/components/ui'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { assignNcr, closeNcr, qcKeys, raiseNcr, recordWork, requestVerification, useNcr, verifyNcr, type Ncr } from '@/api/quality'
import { uploadFiles } from '@/api/files'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { toast } from '@/stores/toast'
import { Fact, FilePick, History, Section, ncrTone } from './parts'

const SEVERITIES = ['Minor', 'Major', 'Critical'].map((s) => ({ value: s, label: s }))
export interface NcrSource { type: string; id: number; ref?: string }

/** Raise a non-conformance: from a failed inspection or a result below criteria, or freestanding. One issue gets one NCR. */
export function NcrModal({ job, from, open, onClose, onRaised }: { job: number; from: NcrSource | null; open: boolean; onClose: () => void; onRaised: (n: Ncr) => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Raise a non-conformance" description={from ? 'What failed is filled in from the record. Add to it if you need to.' : 'Anything not as specified stays open until it is put right and verified.'} size="lg">
      {open && <RaiseForm job={job} from={from} onClose={onClose} onRaised={onRaised} />}
    </Modal>
  )
}

function RaiseForm({ job: initial, from, onClose, onRaised }: { job: number; from: NcrSource | null; onClose: () => void; onRaised: (n: Ncr) => void }) {
  const [job, setJob] = useState(initial)
  const [f, setF] = useState({ description: '', location: '', responsible: '', target_date: '', severity: 'Minor', root_cause: '', corrective_action: '' })
  const [files, setFiles] = useState<File[]>([])
  const [tried, setTried] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const errors = {
    job: from || job ? '' : 'Choose the project.',
    description: from || f.description.trim() ? '' : 'Say what is not as specified.',
    target: f.target_date && f.target_date < today() ? 'The due date is already past.' : '',
  }
  const bad = Object.values(errors).some(Boolean)
  const save = useAction(
    async () => {
      const body = from ? { source_type: from.type, source_id: from.id, source_ref: from.ref ?? '', ...f } : { job_id: job, ...f }
      const r = await raiseNcr(body)
      let failed: string[] = []
      if (files.length) failed = (await uploadFiles(files, 'ncr', r.ncr.id)).failed
      return { ...r, failed }
    },
    { invalidate: [qcKeys.all], success: (r) => `${r.ncr.number} raised`, onSuccess: (r) => { if (r.failed.length) toast.error(`Raised, but not every file was saved: ${r.failed.join(' - ')}`); onRaised(r.ncr); onClose() } },
  )
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        {!from && <Field label="Project" htmlFor="nc-job" error={tried ? errors.job : ''}><ProjectPicker id="nc-job" value={job} onChange={setJob} className="w-full" /></Field>}
        {!from && <Field label="Location" htmlFor="nc-where"><Input id="nc-where" value={f.location} placeholder="Block A, 2nd floor, column C4" onChange={set('location')} /></Field>}
        <Field label={from ? 'Description (optional)' : 'Issue description'} htmlFor="nc-what" error={tried ? errors.description : ''} className="sm:col-span-2"><Textarea id="nc-what" rows={3} value={f.description} placeholder={from ? 'Leave blank to use what the record says failed' : 'What is not as specified, and by how much'} onChange={set('description')} /></Field>
        <Field label="Severity" htmlFor="nc-sev" hint="A major or critical NCR needs its root cause and evidence before it can be verified."><Select id="nc-sev" value={f.severity} onChange={set('severity')} options={SEVERITIES} /></Field>
        <Field label="Due date" htmlFor="nc-by" error={tried ? errors.target : ''}><Input id="nc-by" type="date" min={today()} value={f.target_date} onChange={set('target_date')} /></Field>
        <Field label="Responsible person or contractor" htmlFor="nc-who"><Input id="nc-who" value={f.responsible} placeholder="The contractor, the supplier..." onChange={set('responsible')} /></Field>
        <Field label="Root cause" htmlFor="nc-root"><Input id="nc-root" value={f.root_cause} placeholder="Why it happened, if known" onChange={set('root_cause')} /></Field>
        <Field label="Corrective action" htmlFor="nc-fix" className="sm:col-span-2"><Textarea id="nc-fix" rows={2} value={f.corrective_action} onChange={set('corrective_action')} /></Field>
        <div className="sm:col-span-2"><FilePick files={files} onChange={setFiles} label="Attach photos or documents" /></div>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => (bad ? setTried(true) : save.mutate())}>Raise it</Button>
      </div>
    </div>
  )
}

const STEPS = [['OPEN', 'Open'], ['ASSIGNED', 'Assigned'], ['UNDER_CORRECTION', 'Under correction'], ['REINSPECTION', 'Reinspection'], ['CLOSED', 'Closed']] as const

/** One NCR and what is to be done next, by whoever may do it. */
export function NcrDetail({ id, onClose, onPhotos }: { id: number | null; onClose: () => void; onPhotos: (n: Ncr) => void }) {
  const q = useNcr(id)
  const n = q.data?.ncr
  return (
    <Modal open={!!id} onOpenChange={(o) => !o && onClose()} title={n ? `${n.number}${n.location ? ` - ${n.location}` : ''}` : 'Non-conformance'} size="xl">
      {q.isPending && <Skeleton className="h-48 w-full" />}
      {q.isError && <p role="alert" className="text-[13px] text-danger">{q.error.message}</p>}
      {n && <Body key={`${n.id}-${n.status}-${n.verification_result}`} ncr={n} history={q.data?.history} onClose={onClose} onPhotos={onPhotos} />}
    </Modal>
  )
}

function Body({ ncr: n, history, onClose, onPhotos }: { ncr: Ncr; history?: import('@/api/quality').HistoryLine[]; onClose: () => void; onPhotos: (n: Ncr) => void }) {
  const { can } = useSession()
  const [step, setStep] = useState<'assign' | 'work' | 'ask' | 'verify' | 'reject' | 'close' | null>(null)
  const done = () => setStep(null)
  const at = STEPS.findIndex(([s]) => s === n.status)
  const live = n.status !== 'CLOSED'
  const refresh = { invalidate: [qcKeys.all], onSuccess: done }
  const ask = useAction(() => requestVerification(n.id), { ...refresh, success: 'Sent for verification', onError: done })
  const verify = useAction((v: { result: 'verified' | 'rejected'; note: string }) => verifyNcr(n.id, v.result, v.note), { ...refresh, success: (r) => (r.ncr.verification_result === 'verified' ? 'Verified' : 'Sent back for correction') })
  const close = useAction((note: string) => closeNcr(n.id, note), { ...refresh, success: (r) => `${r.ncr.number} closed` })
  return (
    <div className="grid gap-4">
      <ol aria-label="Progress" className="flex flex-wrap items-center gap-1.5 text-xs">
        {STEPS.map(([s, label], k) => <li key={s} aria-current={k === at ? 'step' : undefined} className={`rounded-full px-2.5 py-1 ring-1 ring-inset ${k === at ? 'bg-primary-soft font-semibold text-primary ring-primary/25' : k < at ? 'text-foreground ring-border' : 'text-muted-foreground ring-border'}`}>{k < at ? '✓ ' : ''}{label}</li>)}
      </ol>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={ncrTone(n.status, n.overdue)} dot>{n.overdue ? 'Late - ' : ''}{n.status_label}</Badge>
        <Badge tone={n.severity === 'Minor' ? 'neutral' : 'danger'}>{n.severity}</Badge>
        {n.verification_result === 'rejected' && <span className="text-xs text-danger">Last correction rejected</span>}
      </div>
      <p className="whitespace-pre-line text-[14px]">{n.description}</p>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact label="Project">{n.project}</Fact>
        <Fact label="Related to">{n.source_number ? `${n.source_number}${n.source_ref ? ` (${n.source_ref}-day)` : ''}` : 'Raised by hand'}</Fact>
        <Fact label="Raised">{formatDate(n.raised_on)} by {n.raised_by}</Fact>
        <Fact label="Due"><span className={n.overdue ? 'font-semibold text-danger' : ''}>{formatDate(n.target_date)}</span></Fact>
        <Fact label="Responsible">{n.responsible}{n.assigned_by && <span className="block text-xs text-muted-foreground">assigned by {n.assigned_by}</span>}</Fact>
        <Fact label="Root cause">{n.root_cause}{n.needs_root_cause && <span className="block text-xs text-warning">Required for a {n.severity.toLowerCase()} NCR</span>}</Fact>
        <Fact label="Corrective action planned">{n.corrective_action}</Fact>
        <Fact label="Evidence">{n.evidence ? `${n.evidence} file${n.evidence === 1 ? '' : 's'}` : 'None attached'}</Fact>
      </dl>
      {n.corrective_done && <Section title="Corrective work recorded"><p className="whitespace-pre-line text-[13.5px]">{n.corrective_done}</p><p className="mt-1 text-xs text-muted-foreground">{formatDate(n.corrective_on)}</p></Section>}
      {n.verification_result && <Section title="Verification"><p className="text-[13.5px]"><span className="font-medium">{n.verification_result === 'verified' ? 'Verified' : 'Rejected'}</span> by {n.verified_by} on {formatDate(n.verified_on)}{n.verification_note && <> - {n.verification_note}</>}{n.reinspection_ref && <> (reinspection {n.reinspection_ref})</>}</p></Section>}
      {n.status === 'CLOSED' && <Section title="Closure"><p className="text-[13.5px]">Closed by {n.closed_by} on {formatDate(n.closed_on)} - {n.closure_note}</p></Section>}
      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {(ask.error || verify.error || close.error) && <p role="alert" className="mr-auto text-[13px] text-danger">{(ask.error ?? verify.error ?? close.error)!.message}</p>}
        <Button variant="outline" onClick={() => onPhotos(n)}><Image /> Evidence</Button>
        <Button variant="outline" asChild><a href={`/api/qc/ncrs/${n.id}/document.pdf`} target="_blank" rel="noopener"><FileText /> PDF</a></Button>
        {live && can('site.signoff') && ['OPEN', 'ASSIGNED', 'UNDER_CORRECTION'].includes(n.status) && <Button variant="outline" onClick={() => setStep('assign')}>{n.status === 'OPEN' ? 'Assign' : 'Reassign'}</Button>}
        {live && can('site.record') && ['ASSIGNED', 'UNDER_CORRECTION'].includes(n.status) && <Button variant="outline" onClick={() => setStep('work')}>Record corrective work</Button>}
        {live && can('site.record') && n.status === 'UNDER_CORRECTION' && <Button onClick={() => setStep('ask')}>Request verification</Button>}
        {live && can('site.signoff') && n.status === 'REINSPECTION' && n.verification_result !== 'verified' && <><Button variant="outline" className="text-danger" onClick={() => setStep('reject')}>Reject</Button><Button onClick={() => setStep('verify')}>Verify</Button></>}
        {live && can('site.signoff') && n.status === 'REINSPECTION' && n.verification_result === 'verified' && <Button onClick={() => setStep('close')}>Close the NCR</Button>}
        <Button variant="ghost" onClick={onClose}>Done</Button>
      </div>
      <Section title="History"><History lines={history} /></Section>

      <AssignModal ncr={n} open={step === 'assign'} onClose={done} />
      <WorkModal ncr={n} open={step === 'work'} onClose={done} />
      <ConfirmDialog open={step === 'ask'} onOpenChange={(o) => !o && done()} title={`Ask for ${n.number} to be verified?`} description={n.severity === 'Minor' ? 'It goes to whoever signs off. Attach photographs of the finished work first if you have them.' : `A ${n.severity.toLowerCase()} NCR needs its root cause and photographs of the work before it can be verified.`} confirmLabel="Request verification" loading={ask.isPending} onConfirm={() => ask.mutate()} />
      <ConfirmDialog open={step === 'verify'} onOpenChange={(o) => !o && done()} title={`Verify the correction on ${n.number}`} description="Confirm the corrective work puts it right." reason={{ label: 'What you checked (optional)' }} confirmLabel="Verified" loading={verify.isPending} onConfirm={(note) => verify.mutate({ result: 'verified', note })} />
      <ConfirmDialog open={step === 'reject'} onOpenChange={(o) => !o && done()} title={`Reject the correction on ${n.number}`} description="It goes back under correction." tone="danger" reason={{ label: 'What is still not right', required: true }} confirmLabel="Reject" loading={verify.isPending} onConfirm={(note) => verify.mutate({ result: 'rejected', note })} />
      <ConfirmDialog open={step === 'close'} onOpenChange={(o) => !o && done()} title={`Close ${n.number}?`} description="It has been verified. Closing records you as the approver and cannot be undone." reason={{ label: 'What was done to put it right', required: true }} confirmLabel="Close it" loading={close.isPending} onConfirm={(note) => close.mutate(note)} />
    </div>
  )
}

function AssignModal({ ncr: n, open, onClose }: { ncr: Ncr; open: boolean; onClose: () => void }) {
  const [f, setF] = useState({ responsible: n.responsible, target_date: n.target_date, corrective_action: n.corrective_action, root_cause: n.root_cause, severity: n.severity })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const bad = !f.responsible.trim() || !f.target_date || f.target_date < today()
  const save = useAction(() => assignNcr(n.id, f), { invalidate: [qcKeys.all], success: (r) => `${r.ncr.number} assigned to ${r.ncr.responsible}`, onSuccess: onClose })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={`Assign ${n.number}`} description="Name who is to put it right, and by when.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Responsible person or contractor" htmlFor="na-who" error={!f.responsible.trim() ? 'Required.' : ''} className="sm:col-span-2"><Input id="na-who" autoFocus value={f.responsible} onChange={set('responsible')} /></Field>
        <Field label="Due date" htmlFor="na-by" error={!f.target_date ? 'Required.' : f.target_date < today() ? 'The due date is already past.' : ''}><Input id="na-by" type="date" min={today()} value={f.target_date} onChange={set('target_date')} /></Field>
        <Field label="Severity" htmlFor="na-sev"><Select id="na-sev" value={f.severity} onChange={set('severity')} options={SEVERITIES} /></Field>
        <Field label="Root cause" htmlFor="na-root" className="sm:col-span-2"><Input id="na-root" value={f.root_cause} onChange={set('root_cause')} /></Field>
        <Field label="Corrective action" htmlFor="na-fix" className="sm:col-span-2"><Textarea id="na-fix" rows={2} value={f.corrective_action} onChange={set('corrective_action')} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={bad} onClick={() => save.mutate()}>Assign</Button>
      </div>
    </Modal>
  )
}

function WorkModal({ ncr: n, open, onClose }: { ncr: Ncr; open: boolean; onClose: () => void }) {
  const [done, setDone] = useState(n.corrective_done)
  const [root, setRoot] = useState(n.root_cause)
  const save = useAction(() => recordWork(n.id, { corrective_done: done, root_cause: root }), { invalidate: [qcKeys.all], success: 'Corrective work recorded. Attach photographs, then request verification.', onSuccess: onClose })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={`Corrective work - ${n.number}`} description="What was actually done to put it right.">
      <div className="grid gap-4">
        <Field label="Work done" htmlFor="nw-done" error={!done.trim() ? 'Say what was done.' : ''}><Textarea id="nw-done" autoFocus rows={3} value={done} onChange={(e) => setDone(e.target.value)} /></Field>
        <Field label="Root cause" htmlFor="nw-root" hint={n.severity !== 'Minor' ? `Required for a ${n.severity.toLowerCase()} NCR.` : undefined}><Input id="nw-root" value={root} onChange={(e) => setRoot(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!done.trim()} onClick={() => save.mutate()}>Save</Button>
      </div>
    </Modal>
  )
}
