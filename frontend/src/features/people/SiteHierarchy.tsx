import { Fragment, useMemo, useState } from 'react'
import { Button, Modal, Skeleton } from '@/components/ui'
import { useEmployees, useHrCatalogue, type Department, type Employee } from '@/api/people'

/** One colour for each row of the chart, top down. Deeper than the last repeats it. */
const TIERS = ['#b8343f', '#0b4f66', '#c4a95f', '#668b9c']
const tier = (row: number) => TIERS[Math.min(row, TIERS.length - 1)]
const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join('')

/**
 * The hierarchy of one department, built from the level each person has been given (L8 Executive down to L1 Trainee):
 * one row for each level that somebody holds, most senior at the top, and each row hangs from the one above. People
 * with no level are in a last row of their own. Choosing a person shows their details here; it does not leave the page.
 */
export function DepartmentHierarchy({ dept }: { dept: Department }) {
  const staff = useEmployees('')
  const catalogue = useHrCatalogue()
  const [shown, setShown] = useState<Employee | null>(null)
  const levels = catalogue.data?.levels ?? []
  const levelLabel = (code: string) => levels.find((l) => l.code === code)?.label ?? code

  const rows = useMemo(() => {
    const people = (staff.data ?? []).filter((e) => e.department_id === dept.id && ['active', 'onboarding'].includes(e.status))
    const byLevel = new Map<string, Employee[]>()
    for (const e of people) byLevel.set(e.level || '', [...(byLevel.get(e.level || '') ?? []), e])
    // The catalogue lists the levels junior to senior, so the chart reads it backwards; unlevelled people come last.
    const order = [...levels.map((l) => l.code).reverse(), ...[...byLevel.keys()].filter((k) => k && !levels.some((l) => l.code === k)), '']
    return order.filter((code) => byLevel.has(code)).map((code) => ({
      code, people: byLevel.get(code)!.sort((a, b) => a.full_name.localeCompare(b.full_name)),
    }))
  }, [staff.data, dept.id, levels])

  if (staff.isPending || catalogue.isPending) return <Skeleton className="h-32 w-full" />
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">Nobody is in {dept.name} yet. Use Edit, then Manage people, to put people in it.</p>

  const card = (e: Employee, row: number) => (
    <button type="button" onClick={() => setShown(e)} aria-label={`${e.full_name}, ${e.job_title || 'no title'}. Show details`} className="group mx-auto block w-44 text-center">
      <span className="relative z-10 mx-auto grid size-16 place-items-center rounded-full border-[3px] bg-white text-lg font-semibold shadow-sm" style={{ borderColor: tier(row), color: tier(row) }}>{initials(e.full_name)}</span>
      <span className="-mt-8 block rounded-sm px-2 pb-2 pt-9 text-white" style={{ background: tier(row) }}>
        <span className="block truncate text-[13px] font-semibold">{e.full_name}</span>
        <span className="block truncate text-[12px] opacity-90">{e.job_title || 'No title'}</span>
        <span className="block text-[11px] opacity-75">{e.level || 'No level set'}</span>
      </span>
    </button>
  )
  const detail = (label: string, value?: string | number | null) => value ? <div><dt className="text-[12px] text-muted-foreground">{label}</dt><dd className="break-words text-sm font-medium">{value}</dd></div> : null
  return (
    <>
      <div className="overflow-x-auto pb-2" aria-label={`${dept.name} hierarchy`}>
        <div className="flex min-w-max flex-col items-center">
          {rows.map((r, i) => (
            <Fragment key={r.code || 'none'}>
              {i > 0 && <div className="lv-stem" style={{ ['--stem' as string]: tier(i - 1) }} />}
              <div className={'lv-row' + (i > 0 ? ' lv-up' : '') + (i < rows.length - 1 ? ' lv-down' : '')} role="group" aria-label={r.code ? levelLabel(r.code) : 'No level set'}
                style={{ ['--up' as string]: tier(i - 1), ['--down' as string]: tier(i) }}>
                {r.people.map((e) => <div key={e.id} className="lv-item">{card(e, i)}{i < rows.length - 1 && <span className="lv-drop" />}</div>)}
              </div>
            </Fragment>
          ))}
        </div>
      </div>
      <Modal open={!!shown} onOpenChange={(o) => !o && setShown(null)} title={shown?.full_name ?? ''} description={shown ? [shown.job_title, dept.name].filter(Boolean).join(' · ') : undefined}
        footer={<Button variant="ghost" onClick={() => setShown(null)}>Close</Button>}>
        {shown && (
          <dl className="grid gap-4 sm:grid-cols-2">
            {detail('Employee ID', shown.employee_id)}
            {detail('Status', shown.status && shown.status[0]!.toUpperCase() + shown.status.slice(1))}
            {detail('Level', shown.level && levelLabel(shown.level))}
            {detail('Reports to', shown.manager_name)}
            {detail('Email', shown.email)}
            {detail('Work email', shown.org_email)}
            {detail('Phone', shown.phone)}
            {detail('Employment', shown.employment_type && shown.employment_type.replace('_', ' '))}
            {detail('Started', shown.start_date)}
          </dl>
        )}
      </Modal>
    </>
  )
}
