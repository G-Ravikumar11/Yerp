import { Link, Route, Routes, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Skeleton } from '@/components/ui'
import { PageHeader } from '@/components/layout/PageHeader'
import IssueForm from '../outward/IssueForm'
import OutwardDoc from '../outward/DocPage'
import { useDoc as useIssue } from '../outward/api'
import GrnForm from '../inward/GrnForm'
import InwardDoc from '../inward/DocPage'
import { useDoc as useGrn } from '../inward/api'
import IssueRegisterPage from './IssueRegisterPage'
import ReceiveRegisterPage from './ReceiveRegisterPage'

export const ISSUES = '/store/issue'
export const RECEIPTS = '/store/receive'

/** The heading over a section's form and document pages, as the Store Hub puts its own over them. */
const Titled = ({ title, children }: { title: string; children: React.ReactNode }) => <div><PageHeader eyebrow="Store" title={title} />{children}</div>

const Back = ({ to, label }: { to: string; label: string }) => (
  <Link to={to} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> {label}</Link>
)

/** The draft to edit, once loaded; only a draft can be. */
function EditGate({ back, label, loading, failed, status, title, children }: { back: string; label: string; loading: boolean; failed: boolean; status?: string; title: string; children: React.ReactNode }) {
  if (loading) return <div><Back to={back} label={label} /><Skeleton className="h-40 w-full" /></div>
  if (failed) return <div><Back to={back} label={label} /><p role="alert" className="text-sm text-danger">Could not load this document.</p></div>
  if (status !== 'DRAFT') return <div><Back to={back} label={label} /><p className="text-sm text-muted-foreground">Only a draft can be edited. Cancel it and make a new one to correct it.</p></div>
  return <div><Back to={back} label={label} /><h2 className="mb-4 text-lg font-semibold">{title}</h2>{children}</div>
}

function IssueEdit() {
  const id = Number(useParams().id)
  const q = useIssue('issue', id)
  return <EditGate back={`${ISSUES}/${id}`} label="Back to the issue" loading={q.isPending} failed={q.isError || !q.data} status={q.data?.status} title={`Edit ${q.data?.number ?? ''}`}><IssueForm doc={q.data} base={ISSUES} /></EditGate>
}

function ReceiveEdit() {
  const id = Number(useParams().id)
  const q = useGrn('grn', id)
  return <EditGate back={`${RECEIPTS}/${id}`} label="Back to the receipt" loading={q.isPending} failed={q.isError || !q.data} status={q.data?.status} title={`Edit ${q.data?.number ?? ''}`}><GrnForm doc={q.data} base={RECEIPTS} /></EditGate>
}

/** Store > Issue: the list, a new issue, one issue (submit, approve, post) and editing a draft - all kept under Store > Issue. */
export function IssueSection() {
  return (
    <Routes>
      <Route index element={<IssueRegisterPage />} />
      <Route path="new" element={<Titled title="Material Issue"><Back to={ISSUES} label="Material issue" /><h2 className="mb-4 text-lg font-semibold">New issue</h2><IssueForm base={ISSUES} /></Titled>} />
      <Route path=":id" element={<Titled title="Material Issue"><OutwardDoc kindKey="issue" base={ISSUES} /></Titled>} />
      <Route path=":id/edit" element={<Titled title="Material Issue"><IssueEdit /></Titled>} />
    </Routes>
  )
}

/** Store > Receive: the list, a new goods receipt, one receipt (quality check, submit, approve, post) and editing a draft. */
export function ReceiveSection() {
  return (
    <Routes>
      <Route index element={<ReceiveRegisterPage />} />
      <Route path="new" element={<Titled title="Material Receive"><Back to={RECEIPTS} label="Material receive" /><h2 className="mb-4 text-lg font-semibold">New goods receipt</h2><GrnForm base={RECEIPTS} /></Titled>} />
      <Route path=":id" element={<Titled title="Material Receive"><InwardDoc kindKey="grn" base={RECEIPTS} /></Titled>} />
      <Route path=":id/edit" element={<Titled title="Material Receive"><ReceiveEdit /></Titled>} />
    </Routes>
  )
}
