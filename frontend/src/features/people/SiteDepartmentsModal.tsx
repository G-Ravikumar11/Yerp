import { useState } from 'react'
import { Button, Input, Modal } from '@/components/ui'
import { peopleKeys, saveDepartment, type Department } from '@/api/people'
import { useAction } from '@/lib/mutate'
import { DEPARTMENT_COLORS } from './icons'

type Site = { id: number; number: string; name: string }

/**
 * Where a site's departments are added and taken off. A department added here belongs to this site and is offered
 * nowhere else. Managing a department's people is offered here, and nowhere else on the page.
 */
export function SiteDepartmentsModal({ site, all, open, onClose, onManage }: {
  site: Site
  /** Every department in the business, so a name already used on another site is reused rather than made twice. */
  all: Department[]
  open: boolean
  onClose: () => void
  onManage: (d: Department) => void
}) {
  const [name, setName] = useState('')
  const onSite = all.filter((d) => d.site_ids.includes(site.id))
  const typed = name.trim()
  const existing = all.find((d) => d.name.trim().toLowerCase() === typed.toLowerCase())
  const already = !!existing && existing.site_ids.includes(site.id)
  const refresh = { invalidate: [peopleKeys.all, ['orders', 'vocabulary']] }

  const add = useAction(() => (existing
    ? saveDepartment(existing.id, { name: existing.name, description: existing.description, color: existing.color, icon: existing.icon, site_ids: [...existing.site_ids, site.id] })
    : saveDepartment(null, { name: typed, description: '', color: DEPARTMENT_COLORS[0], icon: 'building', site_ids: [site.id] })),
  { ...refresh, success: 'Department added', onSuccess: () => setName('') })
  const remove = useAction((d: Department) => saveDepartment(d.id, { name: d.name, description: d.description, color: d.color, icon: d.icon, site_ids: d.site_ids.filter((x) => x !== site.id) }),
    { ...refresh, success: 'Department removed from this site' })

  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="lg" title={`Departments on ${`${site.number} ${site.name}`.trim()}`} description="Add the departments this site needs. A department added here is shown on this site only.">
      {open && (
        <div>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (typed && !already) add.mutate() }}>
            <Input aria-label="Department name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Civil, Accounts, Stores..." autoFocus />
            <Button type="submit" loading={add.isPending} disabled={!typed || already}>Add</Button>
          </form>
          {(already || add.error) && <p role="alert" className="mt-2 text-[13px] text-danger">{already ? `${existing?.name} is already on this site` : add.error?.message}</p>}
          {existing && !already && <p className="mt-2 text-[13px] text-muted-foreground">{existing.name} already exists on another site. It will be added to this one as well, with the same people.</p>}
          {onSite.length === 0 ? <p className="mt-4 text-sm text-muted-foreground">No departments on this site yet.</p> : (
            <ul className="mt-4 divide-y divide-border rounded-lg border border-border">
              {onSite.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{d.name} <span className="font-normal text-muted-foreground">({d.employee_count})</span></span>
                  <Button size="sm" variant="outline" onClick={() => onManage(d)}>Manage people</Button>
                  <Button size="sm" variant="outline" className="text-danger" loading={remove.isPending && remove.variables?.id === d.id} onClick={() => remove.mutate(d)}>Remove</Button>
                </li>
              ))}
            </ul>
          )}
          {remove.error && <p role="alert" className="mt-2 text-[13px] text-danger">{remove.error.message}</p>}
          <div className="mt-5 flex justify-end border-t border-border pt-4"><Button variant="ghost" onClick={onClose}>Done</Button></div>
        </div>
      )}
    </Modal>
  )
}
