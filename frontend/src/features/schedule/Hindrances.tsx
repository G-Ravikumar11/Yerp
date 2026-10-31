import { useState } from 'react'
import { FileSpreadsheet, Pencil, Plus, Trash2 } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select, Stat, StatGrid, Textarea } from '@/components/ui'
import { CAUSES, PARTIES, STATUSES, deleteHindrance, hindranceKeys, registerXlsx, saveHindrance, useRegister, type Hindrance, type HindranceInput } from '@/api/hindrances'
import { schKeys, useSchedule } from '@/api/schedule'
import { diaryKeys } from '@/api/diary'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'

const TONE: Record<string, 'success' | 'danger' | 'warning' | 'neutral'> = { Open: 'warning', Notified: 'neutral', Agreed: 'success', Rejected: 'danger', Closed: 'neutral' }

/** What a hindrance is being opened with: an existing one to change, or a new one (blank, or started from a diary or an activity). */
export type Opening = { hindrance: Hindrance } | { draft: Partial<HindranceInput> }

export function HindranceModal({ job, opening, onClose }: { job: number; opening: Opening | null; onClose: () => void }) {
  const editing = opening && 'hindrance' in opening ? opening.hindrance : null
  return (
    <Modal open={!!opening} onOpenChange={(o) => !o && onClose()} size="lg" title={editing ? `Hindrance ${editing.number}` : 'Record a hindrance'} description="What held the work up, from when to when, whose risk it was, what it cost in days and when the client was told in writing.">
      {opening && <Form key={editing?.id ?? 'new'} job={job} opening={opening} onClose={onClose} />}
    </Modal>
  )
}

function Form({ job, opening, onClose }: { job: number; opening: Opening; onClose: () => void }) {
  const h = 'hindrance' in opening ? opening.hindrance : null
  const start: Partial<HindranceInput> = h ?? ('draft' in opening ? opening.draft : {})
  const acts = useSchedule(job).data?.activities ?? []
  const [cause, setCause] = useState(start.cause || CAUSES[0])
  const [description, setDescription] = useState(start.description ?? '')
  const [from, setFrom] = useState(start.from_date || today())
  const [to, setTo] = useState(start.to_date ?? '')
  const [party, setParty] = useState(start.responsibility ?? '')
  const [days, setDays] = useState<number>(start.impact_days ?? 0)
  // A new one with its days left alone has them counted from its dates by the server; once typed, what is typed is kept.
  const [daysTyped, setDaysTyped] = useState(!!h || (start.impact_days ?? 0) > 0)
  const [notice, setNotice] = useState(start.notice_date ?? '')
  const [status, setStatus] = useState(start.status || 'Open')
  const [activity, setActivity] = useState<number>(start.activity_id ?? 0)
  const save = useAction(
    () => saveHindrance(job, h?.id ?? null, {
      cause, description, from_date: from, to_date: to, responsibility: party, notice_date: notice, activity_id: activity || null,
      // A new one is "Notified" by itself once the notice date is given, unless a status was chosen.
      status: !h && status === 'Open' && notice ? 'Notified' : status,
      ...(daysTyped ? { impact_days: days } : {}),
      ...(!h && start.diary_id ? { diary_id: start.diary_id } : {}),
    } as HindranceInput),
    { invalidate: [hindranceKeys.all, schKeys.all, diaryKeys.all], onSuccess: onClose },
  )
  return (
    <form onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="What held it up" htmlFor="hd-cause"><Select id="hd-cause" value={cause} onChange={(e) => setCause(e.target.value)} options={CAUSES.map((c) => ({ value: c, label: c }))} /></Field>
        <Field label="Whose risk" htmlFor="hd-party"><Select id="hd-party" value={party} onChange={(e) => setParty(e.target.value)} options={[{ value: '', label: 'Not decided yet' }, ...PARTIES.map((p) => ({ value: p, label: p }))]} /></Field>
        <Field label="What happened" htmlFor="hd-desc" className="sm:col-span-2"><Textarea id="hd-desc" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Raft reinforcement drawing not issued; asked for on 2 September" /></Field>
        <Field label="From" htmlFor="hd-from"><Input id="hd-from" type="date" value={from} max={today()} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="To" htmlFor="hd-to" hint="Leave blank while it is still holding the work up."><Input id="hd-to" type="date" value={to} min={from} max={today()} onChange={(e) => setTo(e.target.value)} /></Field>
        <Field label="Days lost" htmlFor="hd-days" hint={daysTyped ? undefined : 'Left at 0, the days from the first to the last are counted.'}><NumField id="hd-days" value={days} onValue={(n) => { setDays(n); setDaysTyped(true) }} /></Field>
        <Field label="Client told in writing on" htmlFor="hd-notice"><Input id="hd-notice" type="date" value={notice} min={from} max={today()} onChange={(e) => setNotice(e.target.value)} /></Field>
        <Field label="Activity it held up" htmlFor="hd-act"><Select id="hd-act" value={String(activity)} onChange={(e) => setActivity(Number(e.target.value))} options={[{ value: '0', label: 'The site as a whole' }, ...acts.map((a) => ({ value: String(a.id), label: `${a.code} ${a.name}`.trim() }))]} /></Field>
        <Field label="Status" htmlFor="hd-status"><Select id="hd-status" value={status} onChange={(e) => setStatus(e.target.value)} options={STATUSES.map((s) => ({ value: s, label: s }))} /></Field>
      </div>
      {party === 'Client' && !notice && <p className="mt-3 rounded-lg border border-warning/40 bg-warning-soft p-2.5 text-[13px]">The client's risk, and not yet told in writing. A delay the client was never told about is hard to claim later.</p>}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={save.isPending}>{h ? 'Save' : 'Add to the register'}</Button>
      </div>
    </form>
  )
}

/** The register as a list: every hindrance on the site, or only those on one activity. */
export function HindranceTable({ rows, loading, canEdit, onOpen, showActivity = true }: { rows: Hindrance[]; loading?: boolean; canEdit: boolean; onOpen: (o: Opening) => void; showActivity?: boolean }) {
  const [removing, setRemoving] = useState<Hindrance | null>(null)
  const remove = useAction((id: number) => deleteHindrance(id), { invalidate: [hindranceKeys.all, schKeys.all], onSuccess: () => setRemoving(null) })
  const columns: TableColumn<Hindrance>[] = [
    { id: 'no', header: 'No.', sort: (r) => r.number, cell: (r) => <span className="font-semibold tabular">{r.number}</span> },
    { id: 'cause', header: 'Cause', cell: (r) => <div className="max-w-72"><div className="font-medium">{r.cause}</div>{r.description && <div className="line-clamp-2 text-xs text-muted-foreground">{r.description}</div>}{showActivity && r.activity && <div className="text-xs text-muted-foreground">on {r.activity}</div>}</div> },
    { id: 'when', header: 'From - to', sort: (r) => r.from_date, cell: (r) => <span className="tabular">{formatDate(r.from_date)} - {r.ongoing ? <span className="text-warning">still going on</span> : formatDate(r.to_date)}</span> },
    { id: 'days', header: 'Days lost', align: 'right', sort: (r) => r.impact_days, cell: (r) => <div><strong className="tabular">{r.impact_days}</strong>{r.running_days !== r.impact_days && <div className="text-xs text-muted-foreground">ran {r.running_days}</div>}</div> },
    { id: 'party', header: 'Whose risk', hideBelow: 'md', cell: (r) => r.responsibility || <span className="text-muted-foreground">not decided</span> },
    { id: 'notice', header: 'Client told', hideBelow: 'md', cell: (r) => (r.notice_date ? formatDate(r.notice_date) : r.notice_due ? <span className="font-medium text-danger">not yet</span> : '-') },
    { id: 'status', header: 'Status', cell: (r) => <Badge tone={TONE[r.status] ?? 'neutral'} dot>{r.status}</Badge> },
    ...(canEdit ? [{
      id: 'act', header: '', align: 'right' as const, cell: (r: Hindrance) => (
        <div className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" aria-label={`Edit ${r.number}`} onClick={() => onOpen({ hindrance: r })}><Pencil /></Button>
          <Button size="sm" variant="ghost" aria-label={`Delete ${r.number}`} onClick={() => setRemoving(r)}><Trash2 /></Button>
        </div>
      ),
    }] : []),
  ]
  return (
    <>
      <DataTable label="Hindrances" rows={rows} columns={columns} rowKey={(r) => r.id} loading={loading} empty="Nothing has held the work up on this site, or it has not been recorded yet." />
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete ${removing?.number ?? ''}?`} description="It goes from the register for good. If it was only settled, close it instead, so the record stays." confirmLabel="Delete" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing.id) }} />
    </>
  )
}

/** The Hindrances tab of Planning & Progress: the site's register, what it adds up to, and the workbook. */
export function HindranceRegister({ job, canEdit }: { job: number; canEdit: boolean }) {
  const q = useRegister(job)
  const s = q.data?.summary
  const [opening, setOpening] = useState<Opening | null>(null)
  return (
    <section aria-label="Hindrance register">
      <div className="mb-3 flex flex-wrap items-center justify-end gap-2">
        <Button variant="outline" asChild><a href={registerXlsx(job)}><FileSpreadsheet /> Excel</a></Button>
        {canEdit && <Button onClick={() => setOpening({ draft: {} })}><Plus /> Hindrance</Button>}
      </div>
      <StatGrid>
        <Stat label="Open" value={s?.open ?? 0} sub={s?.ongoing ? `${s.ongoing} still going on` : undefined} loading={q.isPending} />
        <Stat label="Days lost" value={s?.impact_days ?? 0} loading={q.isPending} />
        <Stat label="On the client" value={`${s?.client_days ?? 0} days`} tone={(s?.client_days ?? 0) > 0 ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Client not yet told" value={s?.notice_due ?? 0} tone={(s?.notice_due ?? 0) > 0 ? 'danger' : undefined} loading={q.isPending} />
      </StatGrid>
      <HindranceTable rows={q.data?.hindrances ?? []} loading={q.isPending} canEdit={canEdit} onOpen={setOpening} />
      <HindranceModal job={job} opening={opening} onClose={() => setOpening(null)} />
    </section>
  )
}
