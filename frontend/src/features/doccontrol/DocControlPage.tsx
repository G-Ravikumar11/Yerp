import { useState } from 'react'
import { BellRing, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Field, Input, Modal, Select, Skeleton, Tabs, Textarea } from '@/components/ui'
import { useProjects, projectLabel } from '@/api/projects'
import { useDrawings } from '@/api/drawings'
import { closeDoc, docKeys, raiseDoc, remindDoc, replyDoc, resubmitDoc, statusText, useDoc, useDocs, type DocItem, type DocKind } from '@/api/docControl'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'

const KINDS: { value: DocKind; label: string; blurb: string }[] = [
  { value: 'TRANSMITTAL', label: 'Transmittals', blurb: 'Drawings and papers sent to a party, at the revision they were at, to be acknowledged.' },
  { value: 'RFI', label: 'RFIs', blurb: 'Questions that need an answer before the work can go on.' },
  { value: 'SUBMITTAL', label: 'Submittals', blurb: 'Material and shop drawings put up for approval. A rejected one goes up again as its next revision.' },
]
const tone = (d: DocItem) => (d.overdue ? 'danger' : d.status === 'OPEN' ? 'warning' : d.status === 'REJECTED' ? 'danger' : d.status === 'CANCELLED' ? 'neutral' : 'success') as 'danger' | 'warning' | 'success' | 'neutral'

/** Projects > Document Control: transmittals, RFIs and submittals, each with a due date, the reply, and reminders. */
export default function DocControlPage() {
  const [kind, setKind] = useState<DocKind>('RFI')
  const [show, setShow] = useState('open')
  const [creating, setCreating] = useState(false)
  const [openId, setOpenId] = useState<number | null>(null)
  const q = useDocs(kind, show)
  const s = q.data?.summary
  const columns: TableColumn<DocItem>[] = [
    { id: 'no', header: 'Number', width: '8rem', sort: (d) => d.id, cell: (d) => <span className="font-mono text-[13px]">{d.number}{d.kind === 'SUBMITTAL' && d.revision ? ` ${d.revision}` : ''}</span> },
    { id: 'subject', header: 'Subject', cell: (d) => <div className="max-w-[26rem]"><div className="truncate font-medium">{d.subject}</div><div className="truncate text-xs text-muted-foreground">{[d.project, `to ${d.to_party}`].filter(Boolean).join(' · ')}</div></div> },
    { id: 'due', header: 'Due', width: '8rem', sort: (d) => d.due_date || '9999', cell: (d) => (d.due_date ? <span className={d.overdue ? 'font-medium text-danger' : ''}>{formatDate(d.due_date)}</span> : <span className="text-muted-foreground">-</span>) },
    { id: 'status', header: 'Status', width: '11rem', cell: (d) => <Badge tone={tone(d)} dot>{d.overdue ? 'overdue' : statusText(d.status)}</Badge> },
  ]
  return (
    <>
      <PageHeader eyebrow="Projects" title="Document Control" description="What went to whom and what came back: transmittals, RFIs and submittals, each with a due date. The other party is reminded before it is due and while it is late."
        actions={<Button onClick={() => setCreating(true)}><Plus /> New {KINDS.find((k) => k.value === kind)!.label.replace(/s$/, '')}</Button>} />
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Tabs label="Kind" value={kind} onChange={(v) => setKind(v as DocKind)} items={KINDS.map((k) => ({ value: k.value, label: k.label, count: s?.[k.value]?.open ?? 0 }))} />
        <Tabs label="Show" value={show} onChange={setShow} items={[{ value: 'open', label: 'Waiting' }, { value: 'replied', label: 'Replied' }, { value: 'closed', label: 'Closed' }, { value: 'all', label: 'All' }]} />
      </div>
      <p className="mb-3 text-sm text-muted-foreground">{KINDS.find((k) => k.value === kind)!.blurb}{s?.[kind]?.overdue ? <strong className="ml-1 text-danger">{s[kind].overdue} overdue.</strong> : null}</p>
      <DataTable label={KINDS.find((k) => k.value === kind)!.label} rows={q.data?.items ?? []} columns={columns} rowKey={(d) => d.id} loading={q.isPending} onRowClick={(d) => setOpenId(d.id)} empty="Nothing here." />
      {creating && <NewDoc kind={kind} purposes={q.data?.purposes ?? []} onClose={() => setCreating(false)} onMade={(id) => { setCreating(false); setOpenId(id) }} />}
      {openId !== null && <DocModal id={openId} onClose={() => setOpenId(null)} />}
    </>
  )
}

function NewDoc({ kind, purposes, onClose, onMade }: { kind: DocKind; purposes: string[]; onClose: () => void; onMade: (id: number) => void }) {
  const projects = useProjects()
  const [f, setF] = useState({ subject: '', to_party: '', to_email: '', job_id: 0, details: '', purpose: kind === 'TRANSMITTAL' ? 'For construction' : kind === 'SUBMITTAL' ? 'For approval' : '', due_date: '' })
  const [picked, setPicked] = useState<number[]>([])
  const [papers, setPapers] = useState('')
  const drawings = useDrawings(f.job_id)
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF({ ...f, [k]: k === 'job_id' ? Number(e.target.value) || 0 : e.target.value })
  const label = KINDS.find((k) => k.value === kind)!.label.replace(/s$/, '')
  const save = useAction(() => raiseDoc({ kind, ...f, job_id: f.job_id || null,
    items: kind === 'TRANSMITTAL' ? [...picked.map((id) => ({ drawing_id: id })), ...papers.split('\n').map((t) => t.trim()).filter(Boolean).map((t) => ({ description: t }))] : [] }),
  { invalidate: [docKeys.all], success: (r) => r.message, onSuccess: (r) => onMade(r.item.id) })
  const missing = !f.subject.trim() ? 'the subject' : !f.to_party.trim() ? 'who it is to' : kind === 'RFI' && !f.details.trim() ? 'the question' : ''
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={`New ${label}`}>
      <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); if (!missing) save.mutate() }}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Subject" htmlFor="dc-subject" className="sm:col-span-2"><Input id="dc-subject" value={f.subject} onChange={set('subject')} autoFocus /></Field>
          <Field label="To" htmlFor="dc-to"><Input id="dc-to" value={f.to_party} onChange={set('to_party')} placeholder="The consultant, the client, a subcontractor" /></Field>
          <Field label="Their email" htmlFor="dc-email" hint="For the reminders."><Input id="dc-email" type="email" value={f.to_email} onChange={set('to_email')} /></Field>
          <Field label="Project" htmlFor="dc-job"><Select id="dc-job" value={f.job_id || ''} placeholder="No particular project" onChange={set('job_id')} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
          <Field label="Reply due by" htmlFor="dc-due" hint="Reminded the day before, and every few days while late."><Input id="dc-due" type="date" min={today()} value={f.due_date} onChange={set('due_date')} /></Field>
          {kind !== 'RFI' && <Field label="Purpose" htmlFor="dc-purpose"><Select id="dc-purpose" value={f.purpose} onChange={set('purpose')} options={purposes.map((p) => ({ value: p, label: p }))} /></Field>}
        </div>
        <Field label={kind === 'RFI' ? 'The question' : kind === 'SUBMITTAL' ? 'What is submitted' : 'Cover note'} htmlFor="dc-details"><Textarea id="dc-details" rows={3} value={f.details} onChange={set('details')} /></Field>
        {kind === 'TRANSMITTAL' && (
          <div className="grid gap-2">
            <p className="text-sm font-medium">Drawings sent {f.job_id ? '' : <span className="font-normal text-muted-foreground">(choose the project to pick its drawings)</span>}</p>
            {f.job_id > 0 && (
              <ul className="grid max-h-44 gap-1 overflow-y-auto rounded-lg border border-border p-2 text-sm">
                {(drawings.data?.drawings ?? []).filter((d) => d.current_revision).map((d) => (
                  <li key={d.id}><label className="flex items-center gap-2"><input type="checkbox" checked={picked.includes(d.id)} onChange={(e) => setPicked((p) => (e.target.checked ? [...p, d.id] : p.filter((x) => x !== d.id)))} /> <span className="font-mono">{d.number}</span> rev {d.current_revision} - {d.title}</label></li>
                ))}
                {(drawings.data?.drawings ?? []).length === 0 && <li className="text-muted-foreground">No drawings on this project's register.</li>}
              </ul>
            )}
            <Field label="Other papers, one a line" htmlFor="dc-papers"><Textarea id="dc-papers" rows={2} value={papers} onChange={(e) => setPapers(e.target.value)} placeholder="Bar bending schedule, 4 sheets" /></Field>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
          {save.error ? <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p> : missing && <p className="mr-auto text-[13px] text-muted-foreground">To raise it, fill in {missing}.</p>}
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!!missing}>Raise {label}</Button>
        </div>
      </form>
    </Modal>
  )
}

function DocModal({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useDoc(id)
  const d = q.data
  const [reply, setReply] = useState('')
  const [response, setResponse] = useState('')
  const [reason, setReason] = useState('')
  const inv = { invalidate: [docKeys.all], success: (r: { message: string }) => r.message }
  const answer = useAction(() => replyDoc(id, reply, response), inv)
  const again = useAction(() => resubmitDoc(id), { ...inv, onSuccess: onClose })
  const close = useAction((cancel: boolean) => closeDoc(id, cancel, reason), inv)
  const remind = useAction(() => remindDoc(id), inv)
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={d ? `${d.number}${d.kind === 'SUBMITTAL' && d.revision ? ` ${d.revision}` : ''} - ${d.subject}` : 'Loading'}>
      {!d ? <Skeleton className="h-40 w-full" /> : (
        <div className="grid gap-4 text-sm">
          <dl className="grid gap-x-6 gap-y-2 rounded-lg border border-border bg-surface/50 p-3 sm:grid-cols-3">
            <div><dt className="text-xs text-muted-foreground">To</dt><dd className="font-medium">{d.to_party}{d.to_email && <div className="text-xs text-muted-foreground">{d.to_email}</div>}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Due</dt><dd className={d.overdue ? 'font-medium text-danger' : 'font-medium'}>{d.due_date ? formatDate(d.due_date) : '-'}{d.overdue && ' (overdue)'}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Status</dt><dd><Badge tone={tone(d)} dot>{statusText(d.status)}</Badge></dd></div>
            <div><dt className="text-xs text-muted-foreground">Project</dt><dd>{d.project || '-'}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Raised</dt><dd>{formatDate(d.created_at.slice(0, 10))} by {d.created_by_name || 'the Master'}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Reminders</dt><dd>{d.reminders ? `${d.reminders}, last ${formatDate(d.reminded_on)}` : 'none yet'}</dd></div>
          </dl>
          {d.details && <p className="whitespace-pre-wrap">{d.details}</p>}
          {(d.items ?? []).length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5">{(d.items ?? []).map((i) => <li key={i.id}>{i.number ? <><span className="font-mono">{i.number}</span> rev {i.revision}{i.description && ` - ${i.description}`}</> : i.description}</li>)}</ul>
          )}
          {d.response && <div className="rounded-lg border border-border p-3"><p className="text-xs text-muted-foreground">Reply{d.responded_on && `, ${formatDate(d.responded_on)}`}{d.responded_by && ` (recorded by ${d.responded_by})`}</p><p className="whitespace-pre-wrap">{d.response}</p></div>}
          {d.status === 'OPEN' && (
            <div className="grid gap-3 rounded-lg border border-border p-3">
              <p className="font-medium">Record the reply</p>
              <div className="flex flex-wrap gap-2">{d.replies.map((r) => <Button key={r} type="button" size="sm" variant={reply === r ? 'primary' : 'outline'} onClick={() => setReply(r)}>{statusText(r)}</Button>)}</div>
              {(d.kind === 'RFI' || reply === 'APPROVED_AS_NOTED' || reply === 'REJECTED') && <Field label={d.kind === 'RFI' ? 'The answer' : 'Their comments'} htmlFor="dc-resp"><Textarea id="dc-resp" rows={3} value={response} onChange={(e) => setResponse(e.target.value)} /></Field>}
              <div className="flex flex-wrap items-center justify-end gap-2">
                {answer.error && <p role="alert" className="mr-auto text-[13px] text-danger">{answer.error.message}</p>}
                {d.to_email && <Button type="button" variant="outline" loading={remind.isPending} onClick={() => remind.mutate()}><BellRing /> Remind {d.to_party} now</Button>}
                <Button type="button" disabled={!reply} loading={answer.isPending} onClick={() => answer.mutate()}>Save the reply</Button>
              </div>
            </div>
          )}
          {d.kind === 'SUBMITTAL' && d.status === 'REJECTED' && <Button className="justify-self-start" loading={again.isPending} onClick={() => again.mutate()}>Resubmit as the next revision</Button>}
          {d.status !== 'CLOSED' && d.status !== 'CANCELLED' && (
            <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
              {d.status !== 'OPEN' && <Button variant="outline" loading={close.isPending && close.variables === false} onClick={() => close.mutate(false)}>Close it</Button>}
              <Field label="Cancel - why" htmlFor="dc-why" className="min-w-52 flex-1"><Input id="dc-why" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Sent in error" /></Field>
              <Button variant="ghost" disabled={reason.trim().length < 3} loading={close.isPending && close.variables === true} onClick={() => close.mutate(true)}>Cancel it</Button>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
