import { useState } from 'react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button, Field, Select, Skeleton } from '@/components/ui'
import { useAllSites, useDepartments, type Department } from '@/api/people'
import { useSession } from '@/lib/session'
import { DepartmentModal } from './DepartmentModal'
import { SiteDepartmentsModal } from './SiteDepartmentsModal'
import { DepartmentHierarchy } from './SiteHierarchy'

export default function DepartmentsPage() {
  const { can } = useSession()
  const canManage = can('people.manage')
  const q = useDepartments()
  const all = q.data ?? []
  const sites = useAllSites().data ?? []
  const [siteId, setSiteId] = useState('')
  const site = sites.find((j) => String(j.id) === siteId) ?? null
  // Nothing is listed until a site is chosen, and then only what was added to that site.
  const onSite = site ? all.filter((d) => d.site_ids.includes(site.id)) : []
  // The department whose chart is open. Choosing another site closes it.
  const [pickedId, setPickedId] = useState<number | null>(null)
  const picked = onSite.find((d) => d.id === pickedId) ?? null
  const [editing, setEditing] = useState(false)
  const [staffing, setStaffing] = useState<Department | null>(null)
  return (
    <>
      <PageHeader eyebrow="People" title="Departments" description="Choose a site to see its departments. Departments are added to a site with Edit, and are shown on that site only. Choose a department to see its hierarchy by level." />
      <div className="mb-5 max-w-sm">
        <Field label="Site" htmlFor="dp-site"><Select id="dp-site" value={siteId} onChange={(e) => { setSiteId(e.target.value); setPickedId(null) }} placeholder="Choose a site" options={sites.map((j) => ({ value: j.id, label: `${j.number} ${j.name}`.trim() }))} /></Field>
      </div>
      {!site ? <p className="text-sm text-muted-foreground">{sites.length === 0 ? 'There are no sites yet. Create a site first, then add its departments here.' : 'Choose a site above.'}</p> : q.isPending ? <Skeleton className="h-24 w-full" /> : (
        <section aria-label={`Departments on ${site.name}`} className="rounded-xl border border-border bg-card p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">{`${site.number} ${site.name}`.trim()}</h2>
            {canManage && <Button size="sm" variant="outline" onClick={() => setEditing(true)}>Edit</Button>}
          </div>
          {onSite.length === 0 ? <p className="mt-3 text-sm text-muted-foreground">No departments on this site yet.{canManage && ' Use Edit to add them.'}</p> : (
            <ul className="mt-3 flex flex-wrap gap-2">
              {onSite.map((x) => (
                <li key={x.id}>
                  <button type="button" aria-pressed={x.id === picked?.id} onClick={() => setPickedId(x.id === picked?.id ? null : x.id)}
                    className={'rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ' + (x.id === picked?.id ? 'border-[var(--primary)] bg-[var(--primary)]/15' : 'border-border hover:bg-muted')}>
                    {x.name} <span className="text-muted-foreground">({x.employee_count})</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {picked && (
        <section aria-label={`${picked.name} hierarchy`} className="mt-5 rounded-xl border border-border bg-card p-5 shadow-card">
          <h2 className="text-lg font-semibold">{picked.name}</h2>
          <p className="mb-5 text-[13px] text-muted-foreground">One row for each level, the most senior at the top. Choose a person to see their details.</p>
          <DepartmentHierarchy dept={picked} />
        </section>
      )}
      {site && <SiteDepartmentsModal key={`site-${site.id}`} site={site} all={all} open={editing} onClose={() => setEditing(false)} onManage={(d) => { setEditing(false); setStaffing(d) }} />}
      <DepartmentModal key={`staff-${staffing?.id ?? 'none'}`} open={!!staffing} dept={staffing} initialTab="people" onClose={() => setStaffing(null)} />
    </>
  )
}
