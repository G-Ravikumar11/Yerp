import { NavLink, Route, Routes, useParams } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { StoreShell } from '../StoreShell'
import { reportOf, REPORTS } from './api'
import OldStoreRecords from '../records/OldStoreRecords'
import AccountsPage from './AccountsPage'
import BudgetUsePage from './BudgetUsePage'
import NormsPage from './NormsPage'
import ReportPage from './ReportPage'

const tab = ({ isActive }: { isActive: boolean }) =>
  cn('whitespace-nowrap rounded-lg px-3.5 py-1.5 text-[13px] font-medium', isActive ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')

function Tabs() {
  return (
    <nav aria-label="Reports" className="mb-4 flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl bg-muted p-1">
      {REPORTS.map((r) => <NavLink key={r.key} to={`/store/hub/reports/${r.key}`} className={tab}>{r.label}</NavLink>)}
      <NavLink to="/store/hub/reports/accounts" className={tab}>For accounts</NavLink>
      <NavLink to="/store/hub/reports/norms" className={tab}>Set norms</NavLink>
      <NavLink to="/store/hub/reports/budget-use" className={tab}>Used vs budget</NavLink>
      <NavLink to="/store/hub/reports/old-store" className={tab}>Old store records</NavLink>
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
        <Route path="accounts" element={<><Tabs /><p className="mb-4 text-sm text-muted-foreground">What accounts take from the stores: stock value, goods received and not billed, scrap sales and cost to charge across projects.</p><AccountsPage /></>} />
        <Route path="norms" element={<><Tabs /><p className="mb-4 text-sm text-muted-foreground">How much of each item a BOQ item should consume. The norms report compares them with what was issued.</p><NormsPage /></>} />
        <Route path="budget-use" element={<><Tabs /><p className="mb-4 text-sm text-muted-foreground">What a project's budget calls for of each material, against what was actually issued to it - from the Hub and from the old store - so overuse shows early.</p><BudgetUsePage /></>} />
        <Route path="old-store/*" element={<><Tabs /><OldStoreRecords /></>} />
        <Route path=":report" element={<One />} />
      </Routes>
    </StoreShell>
  )
}
