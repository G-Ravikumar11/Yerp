import type { QueryClient } from '@tanstack/react-query'

/**
 * Starts reading what a page asks for as it opens, before the page is asked for: the sidebar calls this when the
 * pointer or the keyboard reaches a menu entry, so the answers are on their way - or already here - by the time the
 * page is shown. Each entry uses the very query the page uses, so the page takes the answer from the cache and does
 * not ask again; one read in the last half-minute is not read twice. The modules load only now, so the menu itself
 * carries none of them. Nothing here may fail the page: a refused read is simply not kept.
 */
type Start = (qc: QueryClient) => Promise<unknown>

const PAGES: Record<string, () => Promise<Start>> = {
  '/people/employees': async () => {
    const p = await import('@/api/people')
    return (qc) => Promise.all([qc.prefetchQuery(p.employeesQuery('')), qc.prefetchQuery(p.hrStatsQuery())])
  },
  '/people/departments': async () => {
    const p = await import('@/api/people')
    return (qc) => Promise.all([qc.prefetchQuery(p.departmentsQuery()), qc.prefetchQuery(p.allSitesQuery())])
  },
  '/people/attendance': async () => {
    const a = await import('@/api/attendance')
    return (qc) => Promise.all([qc.prefetchQuery(a.attStatsQuery()), qc.prefetchQuery(a.liveQuery()), qc.prefetchQuery(a.bySiteQuery())])
  },
  '/people/leave': async () => {
    const l = await import('@/api/leave')
    return (qc) => qc.prefetchQuery(l.leaveRequestsQuery())
  },
  '/people/payroll': async () => {
    const p = await import('@/api/payroll')
    return (qc) => Promise.all([qc.prefetchQuery(p.payslipsQuery()), qc.prefetchQuery(p.autoPayrollQuery())])
  },
}

export function prefetchPage(qc: QueryClient, path: string) {
  PAGES[path]?.().then((start) => start(qc)).catch(() => {})
}

/** What the "Add an employee" form fills its pickers from. Started when the button is reached, so they are filled when it opens. */
export function prefetchAddEmployee(qc: QueryClient) {
  void Promise.all([import('@/api/people'), import('@/api/clientOrders')])
    .then(([p, o]) => Promise.all([qc.prefetchQuery(p.hrCatalogueQuery()), qc.prefetchQuery(p.departmentsQuery()), qc.prefetchQuery(p.employeesQuery('')), qc.prefetchQuery(o.jobOptionsQuery(false))]))
    .catch(() => {})
}
