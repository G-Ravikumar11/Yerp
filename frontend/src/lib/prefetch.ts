import type { QueryClient } from '@tanstack/react-query'
import { matchPath } from 'react-router-dom'
import { SCREENS } from '@/routes'

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
  preloadScreen(path)
  PAGES[path]?.().then((start) => start(qc)).catch(() => {})
}

/* --- a screen's code, loaded before it is opened ------------------------------------------------------------------- */

const asked = new Set<string>()

/** Start loading the code of the screen at `path`, once. A failed load is forgotten, so the click itself tries again. */
export function preloadScreen(path: string) {
  if (asked.has(path)) return
  const screen = SCREENS.find((s) => matchPath({ path: s.path, end: true }, path))
  if (!screen?.Component.preload) return
  asked.add(path)
  screen.Component.preload().catch(() => asked.delete(path))
}

type Connection = { saveData?: boolean; effectiveType?: string }

/**
 * The screens of the menu, loaded quietly while the browser has nothing else to do - two at a time, after the page in
 * front of the person has finished loading - so the first visit to any of them is as quick as the second. Not on a
 * connection that asks to save data or is too slow to spare it.
 */
export function preloadScreens(paths: string[]) {
  const conn = (navigator as Navigator & { connection?: Connection }).connection
  if (conn?.saveData || /(^|-)2g$/.test(conn?.effectiveType ?? '')) return
  const queue = paths.filter((p) => !asked.has(p))
  const idle = (fn: () => void) => ('requestIdleCallback' in window ? window.requestIdleCallback(fn, { timeout: 4000 }) : setTimeout(fn, 1500))
  const next = () => {
    const batch = queue.splice(0, 2)
    if (!batch.length) return
    batch.forEach(preloadScreen)
    idle(next)
  }
  // Wait for the screen in front to settle first: its own code and data come before anything ahead.
  setTimeout(() => idle(next), 2500)
}

/** What the "Add an employee" form fills its pickers from. Started when the button is reached, so they are filled when it opens. */
export function prefetchAddEmployee(qc: QueryClient) {
  void Promise.all([import('@/api/people'), import('@/api/clientOrders')])
    .then(([p, o]) => Promise.all([qc.prefetchQuery(p.hrCatalogueQuery()), qc.prefetchQuery(p.departmentsQuery()), qc.prefetchQuery(p.employeesQuery('')), qc.prefetchQuery(o.jobOptionsQuery(false))]))
    .catch(() => {})
}
