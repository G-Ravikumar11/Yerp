import { useState } from 'react'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button, ConfirmDialog, Skeleton } from '@/components/ui'
import { deleteDepartment, peopleKeys, useDepartments, type Department } from '@/api/people'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { DepartmentModal } from './DepartmentModal'
import { iconOf } from './icons'

export default function DepartmentsPage() {
  const { isOwner } = useSession()
  const q = useDepartments()
  const [editing, setEditing] = useState<Department | null>(null)
  const [creating, setCreating] = useState(false)
  const [removing, setRemoving] = useState<Department | null>(null)
  const remove = useAction((d: Department) => deleteDepartment(d.id), { invalidate: [peopleKeys.all, ['orders', 'vocabulary']], success: 'Department deleted', onSuccess: () => setRemoving(null) })
  return (
    <>
      <PageHeader eyebrow="People" title="Departments" description="The departments of the business. Create them here and they appear everywhere they are needed: on an employee, on a work order, and on a member of staff's own sign-in." actions={isOwner && <Button onClick={() => setCreating(true)}><Plus /> New department</Button>} />
      {q.isPending ? <Skeleton className="h-40 w-full" /> : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {(q.data ?? []).map((d) => {
            const Icon = iconOf(d.icon)
            return (
              <section key={d.id} aria-label={d.name} className="rounded-xl border border-border bg-card p-4 shadow-card">
                <div className="flex items-start gap-3">
                  <span className="grid size-10 shrink-0 place-items-center rounded-lg text-white" style={{ background: d.color }}><Icon className="size-5" /></span>
                  <div className="min-w-0 flex-1"><h2 className="truncate font-semibold">{d.name}</h2><p className="line-clamp-2 text-[13px] text-muted-foreground">{d.description || 'No description'}</p></div>
                </div>
                <p className="mt-3 text-sm"><strong>{d.employee_count}</strong> {d.employee_count === 1 ? 'person' : 'people'}</p>
                <ul className="mt-1 min-h-10 text-[13px] text-muted-foreground">{d.employees.slice(0, 4).map((e) => <li key={e.id} className="truncate">{e.name}{e.job_title && ` - ${e.job_title}`}</li>)}{d.employees.length > 4 && <li>and {d.employees.length - 4} more</li>}</ul>
                {isOwner && <div className="mt-3 flex gap-2"><Button size="sm" variant="outline" onClick={() => setEditing(d)}>Edit</Button><Button size="sm" variant="outline" className="text-danger" onClick={() => setRemoving(d)}>Delete</Button></div>}
              </section>
            )
          })}
          {q.data?.length === 0 && <p className="col-span-full rounded-lg border border-border bg-muted/40 p-4 text-sm">No departments yet. Until you create some, work orders offer the usual trades (Civil, STP, Electrical...). Create yours and they replace them.</p>}
        </div>
      )}
      <DepartmentModal open={creating || !!editing} dept={editing} onClose={() => { setCreating(false); setEditing(null) }} />
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete ${removing?.name ?? 'this department'}?`} description="The people in it are not deleted; they are left with no department." confirmLabel="Delete it" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing) }} />
    </>
  )
}
