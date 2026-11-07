import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Lock, LockOpen } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, ConfirmDialog, Skeleton, Stat, StatGrid } from '@/components/ui'
import { JOB_STATUS, lockProject, unlockProject, useProject, type ProjectDoc } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate as fmt } from '@/lib/format'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { ProjectFormModal } from './ProjectFormModal'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

function Docs({ title, rows, party }: { title: string; rows: ProjectDoc[]; party: (d: ProjectDoc) => string }) {
  if (!rows.length) return null
  const columns: TableColumn<ProjectDoc>[] = [
    { id: 'no', header: title.replace(/s$/, ''), cell: (d) => <span className="font-mono text-[13px] font-semibold">{d.number}</span> },
    { id: 'who', header: 'With', hideBelow: 'md', cell: (d) => party(d) },
    { id: 'date', header: 'Date', hideBelow: 'md', cell: (d) => formatDate(d.issue_date) },
    { id: 'total', header: 'Total', align: 'right', cell: (d) => formatINR(d.total) },
    { id: 'status', header: 'Status', cell: (d) => <span>{d.status}{d.over_order && <span className="ml-1.5 text-xs text-danger">over order</span>}</span> },
  ]
  return <section aria-label={title} className="mb-6"><h2 className="mb-2 text-sm font-semibold">{title}</h2><DataTable label={title} rows={rows} columns={columns} rowKey={(d) => d.id} /></section>
}

/** One project: where the money stands, and every paper filed against it. */
export default function ProjectPage() {
  const id = Number(useParams().id)
  const nav = useNavigate()
  const q = useProject(id)
  const [editing, setEditing] = useState(false)
  const [locking, setLocking] = useState<'lock' | 'unlock' | null>(null)
  const { isOwner } = useSession()
  const lockIt = useAction((reason: string) => (locking === 'unlock' ? unlockProject(id) : lockProject(id, reason)), { invalidate: [['projects'], ['jobs']], success: (r) => r.message, onSuccess: () => setLocking(null) })
  const p = q.data
  const c = p?.costing
  const cls = c ? (c.over_budget ? 'text-danger' : 'text-success') : ''
  const none = p && !p.invoices.length && !p.bills.length && !p.purchase_orders.length && !p.quotes.length
  return (
    <>
      <Link to="/projects" className="mb-3 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground"><ArrowLeft className="size-3.5" /> All projects</Link>
      {q.isError ? (
        <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">This project no longer exists. It may have been deleted. <Link to="/projects" className="font-medium text-primary underline underline-offset-4">Back to all projects</Link></p>
      ) : q.isPending || !p || !c ? <Skeleton className="h-64 w-full" /> : (
        <>
          <PageHeader title={`${p.number} - ${p.name}`} description={[p.customer_name, p.site_address, JOB_STATUS[p.status] ?? p.status].filter(Boolean).join(' - ')} actions={<>{isOwner && (p.locked ? <Button variant="outline" onClick={() => setLocking('unlock')}><LockOpen /> Unlock</Button> : <Button variant="outline" onClick={() => setLocking('lock')}><Lock /> Lock</Button>)}<Button variant="outline" disabled={!!p.locked} onClick={() => setEditing(true)}>Edit</Button><MasterDelete kind="project" id={p.id} label={`${p.number} ${p.name}`} noun="project" onDeleted={() => nav('/projects')} /></>} />
          {p.locked && (
            <p role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-soft p-3 text-sm text-danger">
              <Lock className="mt-0.5 size-4 shrink-0" />
              <span><strong>Locked by {p.locked_by_name || 'the Master'}{p.locked_at ? ` on ${fmt(p.locked_at)}` : ''}.</strong> {p.lock_reason} Nothing on this project can be changed by anybody until the Master unlocks it.</span>
            </p>
          )}
          {c.over_budget && <p role="alert" className="mb-4 rounded-lg border border-danger/30 bg-danger-soft p-3 text-sm font-semibold text-danger">Costs and open orders have passed the {formatINR(c.budget)} budget.</p>}
          <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
            <Stat label="Quoted" value={formatINR(c.quoted)} />
            <Stat label="Budget" value={formatINR(c.budget)} />
            <Stat label="Used budget" value={formatINR(c.used)} />
            <Stat label="Remaining budget" value={<span className={cls}>{c.budget ? formatINR(c.remaining) : '-'}</span>} />
            <Stat label="Cost so far" value={formatINR(c.total_cost)} />
            <Stat label="Labour" value={formatINR(c.labour_cost)} sub={`${c.labour_hours}h`} />
          </StatGrid>
          {none && <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">Nothing filed against this project yet.</p>}
          <Docs title="Invoices" rows={p.invoices} party={(d) => d.to_contact ?? ''} />
          <Docs title="Purchase orders" rows={p.purchase_orders} party={(d) => d.supplier_name ?? ''} />
          <Docs title="Bills" rows={p.bills} party={(d) => d.vendor_name ?? ''} />
          <Docs title="Quotes" rows={p.quotes} party={() => ''} />
          <ProjectFormModal project={p} open={editing} onClose={() => setEditing(false)} />
          <ConfirmDialog
            open={!!locking} onOpenChange={(o) => !o && setLocking(null)}
            title={locking === 'unlock' ? `Unlock ${p.number}?` : `Lock ${p.number}?`}
            description={locking === 'unlock' ? 'Everybody can work on it again as before.' : 'Nobody - staff, your team or you - can change anything on this project: its BOQ, orders, bills, store, diary, drawings, quality and safety records. It can still be read. Only you can unlock it.'}
            confirmLabel={locking === 'unlock' ? 'Unlock' : 'Lock the project'} tone={locking === 'unlock' ? undefined : 'danger'}
            reason={locking === 'unlock' ? undefined : { label: 'Why is it being locked? Everybody who tries to change it is told.', required: true }}
            loading={lockIt.isPending} onConfirm={(reason) => lockIt.mutate(reason ?? '')}
          />
        </>
      )}
    </>
  )
}
