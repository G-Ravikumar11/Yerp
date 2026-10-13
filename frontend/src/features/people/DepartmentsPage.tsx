import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button, ConfirmDialog, Skeleton } from '@/components/ui'
import { deleteDepartment, peopleKeys, showDepartmentChange, useDepartments, type Department } from '@/api/people'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { DepartmentModal } from './DepartmentModal'
import { iconOf } from './icons'

export default function DepartmentsPage() {
  const { isOwner } = useSession()
  const qc = useQueryClient()
  const q = useDepartments()
  const depts = q.data ?? []
  const [picked, setPicked] = useState<number | null>(null)
  // Nothing is open until one is picked; if the picked one is deleted the page goes back to the list.
  const d = depts.find((x) => x.id === picked)
  const [editing, setEditing] = useState<Department | null>(null)
  const [creating, setCreating] = useState(false)
  const [removing, setRemoving] = useState<Department | null>(null)
  // Gone from the page the moment it is confirmed; a refusal reloads the list and says why.
  const remove = useAction((d: Department) => deleteDepartment(d.id), { success: 'Department deleted', onSuccess: (_, d) => showDepartmentChange(qc, { deletedId: d.id }), onError: () => void qc.invalidateQueries({ queryKey: peopleKeys.all }) })
  const confirmDelete = () => {
    if (!removing) return
    const d = removing
    setRemoving(null)
    showDepartmentChange(qc, { deletedId: d.id }, { refresh: false })
    remove.mutate(d)
  }
  return (
    <>
      <PageHeader eyebrow="People" title="Departments" description="The departments of the business. Create them here and they appear everywhere they are needed: on an employee, on a work order, and on a member of staff's own sign-in." actions={isOwner && <Button onClick={() => setCreating(true)}><Plus /> New department</Button>} />
      {q.isPending ? <Skeleton className="h-40 w-full" /> : depts.length === 0 ? (
        <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No departments yet. Until you create some, work orders offer the usual trades (Civil, STP, Electrical...). Create yours and they replace them.</p>
      ) : (
        <>
          <div role="tablist" aria-label="Departments" className="mb-5 flex flex-wrap gap-2">
            {depts.map((x) => (
              <button key={x.id} role="tab" aria-selected={x.id === d?.id} onClick={() => setPicked(x.id)}
                className={'rounded-lg border px-3.5 py-2 text-sm font-medium transition-colors ' + (x.id === d?.id ? 'border-[var(--primary)] bg-[var(--primary)]/15 text-foreground' : 'border-border bg-card text-muted-foreground hover:text-foreground')}>
                {x.name} ({x.employee_count})
              </button>
            ))}
          </div>
          {!d && <p className="text-sm text-muted-foreground">Select a department to see its people.</p>}
          {d && (() => {
            const Icon = iconOf(d.icon)
            return (
              <section aria-label={d.name} className="rounded-xl border border-border bg-card p-5 shadow-card">
                <div className="flex flex-wrap items-start gap-3">
                  <span className="grid size-11 shrink-0 place-items-center rounded-lg text-white" style={{ background: d.color }}><Icon className="size-5" /></span>
                  <div className="min-w-0 flex-1"><h2 className="text-lg font-semibold">{d.name} <span className="text-muted-foreground">({d.employee_count})</span></h2><p className="text-[13px] text-muted-foreground">{d.description || 'No description'}</p></div>
                  {isOwner && <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setEditing(d)}>Edit</Button><Button size="sm" variant="outline" className="text-danger" onClick={() => setRemoving(d)}>Delete</Button></div>}
                </div>
                {d.employees.length === 0 ? <p className="mt-5 text-sm text-muted-foreground">Nobody is in this department yet.</p> : (
                  <ul className="mt-5 divide-y divide-border rounded-lg border border-border">
                    {d.employees.map((e) => (
                      <li key={e.id}>
                        <Link to={`/people/employees/${e.id}`} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5 text-sm hover:bg-muted">
                          <span className="font-medium">{e.name}</span>
                          <span className="text-[13px] text-muted-foreground">{[e.job_title, e.email].filter(Boolean).join(' · ')}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )
          })()}
        </>
      )}
      <DepartmentModal key={editing?.id ?? (creating ? 'new' : 'closed')} open={creating || !!editing} dept={editing} onClose={() => { setCreating(false); setEditing(null) }} />
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete ${removing?.name ?? 'this department'}?`} description="The people in it are not deleted; they are left with no department." confirmLabel="Delete it" tone="danger" onConfirm={confirmDelete} />
    </>
  )
}
