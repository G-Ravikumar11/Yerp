import { NavLink, Route, Routes, useParams } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { StoreShell } from '../StoreShell'
import { reportOf, REPORTS } from './api'
import NormsPage from './NormsPage'
import ReportPage from './ReportPage'

const tab = ({ isActive }: { isActive: boolean }) =>
  cn('whitespace-nowrap rounded-lg px-3.5 py-1.5 text-[13px] font-medium', isActive ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')

function Tabs() {
  return (
    <nav aria-label="Reports" className="mb-4 flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl bg-muted p-1">
      {REPORTS.map((r) => <NavLink key={r.key} to={`/store/hub/reports/${r.key}`} className={tab}>{r.label}</NavLink>)}
      <NavLink to="/store/hub/reports/norms" className={tab}>Set norms</NavLink>
    </nav>
  )
}

function One() {
  const { report } = useParams()
  const r = reportOf(report) ?? REPORTS[0]
  return (
    <>
      <Tabs />
      <p className="mb-4 text-sm text-muted-foreground">{r.blurb}</p>
      <ReportPage key={r.key} report={r.key} />
    </>
  )
}

/** Store > Reports. Routes under /store/hub/reports/* land here. */
export default function ReportsIndex() {
  return (
    <StoreShell slice="reports">
      <Routes>
        <Route index element={<One />} />
        <Route path="norms" element={<><Tabs /><p className="mb-4 text-sm text-muted-foreground">How much of each item a BOQ item should consume. The norms report compares them with what was issued.</p><NormsPage /></>} />
        <Route path=":report" element={<One />} />
      </Routes>
    </StoreShell>
  )
}
