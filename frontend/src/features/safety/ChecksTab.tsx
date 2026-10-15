import { useState } from 'react'
import { FileSpreadsheet, FileText, Plus, Trash2 } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Stat, StatGrid, Tabs } from '@/components/ui'
import { removeCheck, safetyKeys, useChecks, type Check } from '@/api/safety'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { CheckFormModal } from './CheckForm'
import { CheckDetail } from './CheckDetail'

const dueText = (c: Check) => (c.due_in_days === null ? '' : c.due_in_days < 0 ? `${-c.due_in_days} day${c.due_in_days === -1 ? '' : 's'} overdue` : c.due_in_days === 0 ? 'due today' : `in ${c.due_in_days} day${c.due_in_days === 1 ? '' : 's'}`)

/**
 * Equipment checks: the company's inspection checklists - portable grinder, breaking machine, hammer drill, fire
 * extinguisher and electrical board. Each is answered item by item with photos, readings and sign-offs; a fault is
 * flagged, the next inspection falls due, and the client / PMC accepts or rejects it.
 */
export function ChecksTab({ job }: { job: number }) {
  const { can } = useSession()
  const [form, setForm] = useState('')
  const q = useChecks(job, form)
  const [creating, setCreating] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const [removing, setRemoving] = useState<Check | null>(null)
  const remove = useAction((c: Check) => removeCheck(c.id), { invalidate: [safetyKeys.all], success: 'Inspection removed', onSuccess: () => setRemoving(null) })
  const d = q.data
  const s = d?.summary
  const opened = d?.checks.find((c) => c.id === open)
  const query = new URLSearchParams({ ...(job ? { job_id: String(job) } : {}), ...(form ? { form_type: form } : {}) }).toString()

  const columns: TableColumn<Check>[] = [
    { id: 'no', header: 'No.', cell: (c) => <span className="font-mono text-[13px]">{c.number}</span> },
    { id: 'what', header: 'Checklist', cell: (c) => <div>{c.form_label}<div className="text-xs text-muted-foreground">{c.doc_ref}</div></div> },
    { id: 'eq', header: 'Equipment', sort: (c) => c.equipment_no, cell: (c) => <div className="font-medium">{c.equipment_no}{c.location && <div className="text-xs font-normal text-muted-foreground">{c.location}</div>}</div> },
    { id: 'proj', header: 'Project', hideBelow: 'xl', cell: (c) => c.project },
    { id: 'on', header: 'Inspected', sort: (c) => c.inspection_date, hideBelow: 'md', cell: (c) => formatDate(c.inspection_date) },
    {
      id: 'next', header: 'Next due', sort: (c) => c.next_inspection_date || '9999', hideBelow: 'md',
      cell: (c) => !c.next_inspection_date ? '-' : (
        <div>{formatDate(c.next_inspection_date)}
          {c.current ? <div className={'text-xs ' + (c.due_state === 'overdue' ? 'font-semibold text-danger' : c.due_state === 'soon' ? 'text-warning' : 'text-muted-foreground')}>{dueText(c)}</div>
            : <div className="text-xs text-muted-foreground">inspected again since</div>}
        </div>
      ),
    },
    { id: 'res', header: 'Result', cell: (c) => <Badge tone={c.result === 'fail' ? 'danger' : 'success'} dot>{c.result === 'fail' ? `Fault${c.failed.length ? ` (${c.failed.length})` : ''}` : 'Passed'}</Badge> },
    { id: 'rev', header: 'Client / PMC', hideBelow: 'lg', cell: (c) => !c.has_review ? <span className="text-muted-foreground">-</span> : <Badge tone={c.decision === 'accepted' ? 'success' : c.decision === 'rejected' ? 'danger' : 'warning'} dot>{c.decision === 'accepted' ? 'Accepted' : c.decision === 'rejected' ? 'Rejected' : 'Awaiting'}</Badge> },
    {
      id: 'act', header: '', align: 'right',
      cell: (c) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" onClick={() => setOpen(c.id)}>Open</Button>
          <Button size="sm" variant="outline" asChild><a href={`/api/safety/checks/${c.id}/document.pdf`} target="_blank" rel="noopener"><FileText /> PDF</a></Button>
          {can('site.signoff') && <Button size="icon" variant="ghost" aria-label={`Remove ${c.number}`} onClick={() => setRemoving(c)}><Trash2 /></Button>}
        </div>
      ),
    },
  ]
  const forms = d?.forms ?? []
  return (
    <>
      <StatGrid className="mb-4 lg:grid-cols-3 xl:grid-cols-5">
        <Stat label="Equipment inspected" value={s?.equipment ?? 0} sub={s ? `${s.total} inspections in all` : undefined} loading={q.isPending} />
        <Stat label="With a fault" value={s?.failed ?? 0} tone={s?.failed ? 'danger' : undefined} sub="latest inspection found one" loading={q.isPending} />
        <Stat label="Overdue" value={s?.overdue ?? 0} tone={s?.overdue ? 'danger' : undefined} sub="next inspection date has passed" loading={q.isPending} />
        <Stat label="Due this week" value={s?.due_soon ?? 0} tone={s?.due_soon ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Awaiting the client / PMC" value={s?.awaiting_review ?? 0} tone={s?.awaiting_review ? 'warning' : undefined} loading={q.isPending} />
      </StatGrid>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="max-w-full overflow-x-auto"><Tabs label="Checklist" value={form} onChange={setForm} items={[{ value: '', label: 'All' }, ...forms.map((f) => ({ value: f.key, label: f.label }))]} /></div>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button variant="outline" asChild><a href={`/api/safety/checks.xlsx${query ? `?${query}` : ''}`}><FileSpreadsheet /> Register</a></Button>
          <Button disabled={!job || !forms.length} title={job ? undefined : 'Choose a project first.'} onClick={() => setCreating(true)}><Plus /> New inspection</Button>
        </div>
      </div>
      <DataTable label="Equipment checks" rows={d?.checks ?? []} columns={columns} rowKey={(c) => c.id} loading={q.isPending}
        empty={job ? 'No inspections yet. Tools, extinguishers and electrical boards are checked before use and again when the next date falls due.' : 'No inspections yet. Choose a project to record one.'} />
      <CheckFormModal job={job} forms={forms} open={creating} onClose={() => setCreating(false)} />
      {opened && <CheckDetail check={opened} form={forms.find((f) => f.key === opened.form_type)} onClose={() => setOpen(null)} />}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={removing ? `Remove ${removing.number}?` : ''} description="The inspection and its photographs are taken off the record. It cannot be undone." confirmLabel="Remove" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing) }} />
    </>
  )
}
