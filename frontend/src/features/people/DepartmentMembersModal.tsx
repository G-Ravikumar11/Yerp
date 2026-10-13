import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { Button, Input, Modal } from '@/components/ui'
import { addToDepartment, peopleKeys, removeFromDepartment, showDepartmentChange, useEmployees, type Department, type Employee } from '@/api/people'
import { useAction } from '@/lib/mutate'

/** Who is in a department: take people out, or bring them in - from no department or from another one. */
export function DepartmentMembersModal({ dept, onClose }: { dept: Department | null; onClose: () => void }) {
  return (
    <Modal open={!!dept} onOpenChange={(o) => !o && onClose()} size="lg" title={dept ? `People in ${dept.name}` : ''} description="Adding somebody who is in another department moves them here.">
      {dept && <Members key={dept.id} dept={dept} onClose={onClose} />}
    </Modal>
  )
}

export function Members({ dept, onClose }: { dept: Department; onClose: () => void }) {
  const qc = useQueryClient()
  const people = useEmployees('')
  const [picked, setPicked] = useState<number[]>([])
  const [q, setQ] = useState('')
  // Shown the moment it is clicked, then put right from the server's answer; a refusal reloads what is really there.
  const undo = () => void qc.invalidateQueries({ queryKey: peopleKeys.all })
  const add = useAction((ids: number[]) => addToDepartment(dept.id, ids), { success: (d) => `${d.name} now has ${d.employee_count} ${d.employee_count === 1 ? 'person' : 'people'}`, onSuccess: (d) => showDepartmentChange(qc, { saved: d }), onError: undo })
  const remove = useAction((id: number) => removeFromDepartment(dept.id, id), { success: 'Taken out of the department', onSuccess: (d) => showDepartmentChange(qc, { saved: d }), onError: undo })

  const inside = (people.data ?? []).filter((e) => e.department_id === dept.id)
  const preview = (members: Employee[]) => showDepartmentChange(qc, { saved: { ...dept, employee_count: members.length, employees: members.map((e) => ({ id: e.id, name: e.full_name, job_title: e.job_title, email: e.email, status: e.status })) } }, { refresh: false })
  const addPicked = () => {
    const ids = picked
    preview([...inside, ...(people.data ?? []).filter((e) => ids.includes(e.id))])
    setPicked([])
    add.mutate(ids)
  }
  const takeOut = (id: number) => {
    preview(inside.filter((e) => e.id !== id))
    remove.mutate(id)
  }
  const needle = q.trim().toLowerCase()
  const outside = (people.data ?? []).filter((e) => e.department_id !== dept.id && (!needle || e.full_name.toLowerCase().includes(needle) || (e.department_name || '').toLowerCase().includes(needle)))
  const toggle = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  return (
    <div className="grid gap-5 md:grid-cols-2">
      <section aria-label="In this department">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">In {dept.name} ({inside.length})</h3>
        {inside.length === 0 && <p className="text-[13px] text-muted-foreground">Nobody yet.</p>}
        <ul className="max-h-80 divide-y divide-border overflow-y-auto rounded-lg border border-border">
          {inside.map((e) => (
            <li key={e.id} className="flex items-center gap-2 px-3 py-2 text-[13px]">
              <span className="min-w-0 flex-1 truncate">{e.full_name}{e.job_title && <span className="text-muted-foreground"> · {e.job_title}</span>}</span>
              <Button size="sm" variant="ghost" aria-label={`Take ${e.full_name} out of ${dept.name}`} onClick={() => takeOut(e.id)}><X /></Button>
            </li>
          ))}
        </ul>
      </section>
      <section aria-label="Add people">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Add people</h3>
        <Input aria-label="Search people" placeholder="Search by name or department" value={q} onChange={(e) => setQ(e.target.value)} />
        <ul className="mt-2 max-h-72 divide-y divide-border overflow-y-auto rounded-lg border border-border">
          {outside.map((e) => (
            <li key={e.id}>
              <label className="flex items-center gap-2 px-3 py-2 text-[13px]">
                <input type="checkbox" className="size-4 accent-[var(--primary)]" checked={picked.includes(e.id)} onChange={() => toggle(e.id)} />
                <span className="min-w-0 flex-1 truncate">{e.full_name}</span>
                <span className="shrink-0 text-muted-foreground">{e.department_name ? `in ${e.department_name}` : 'no department'}</span>
              </label>
            </li>
          ))}
          {people.isSuccess && outside.length === 0 && <li className="px-3 py-2 text-[13px] text-muted-foreground">Nobody else to add.</li>}
        </ul>
      </section>
      <div className="flex items-center justify-end gap-2 border-t border-border pt-4 md:col-span-2">
        {(add.error || remove.error) && <p role="alert" className="mr-auto text-[13px] text-danger">{(add.error || remove.error)?.message}</p>}
        <Button variant="ghost" onClick={onClose}>Done</Button>
        <Button disabled={picked.length === 0} onClick={addPicked}>{picked.length > 1 ? `Add ${picked.length} people` : 'Add to department'}</Button>
      </div>
    </div>
  )
}
