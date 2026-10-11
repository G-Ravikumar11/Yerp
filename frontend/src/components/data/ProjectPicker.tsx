import { useEffect } from 'react'
import { Select } from '@/components/ui'
import { projectLabel, useProjects } from '@/api/projects'

/**
 * Choose the site a screen is about. Picks the first project once they load, so a screen
 * opens on something rather than on an empty choice; `value` is 0 until then.
 */
export function ProjectPicker({ value, onChange, id = 'project', allowAll = false, className }: { value: number; onChange: (id: number) => void; id?: string; allowAll?: boolean; className?: string }) {
  const q = useProjects()
  const jobs = q.data
  useEffect(() => {
    if (!allowAll && !value && jobs?.length) onChange(jobs[0].id)
  }, [allowAll, value, jobs, onChange])
  return (
    <div className={className ?? 'w-full max-w-md'}>
      <Select id={id} aria-label="Project" value={value || ''} disabled={q.isPending} placeholder={allowAll ? 'All projects' : q.isPending ? 'Loading projects...' : jobs?.length ? undefined : 'No projects yet'} options={(jobs ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} onChange={(e) => onChange(Number(e.target.value) || 0)} />
    </div>
  )
}
