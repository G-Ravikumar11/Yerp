import { Navigate, useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button, Tabs } from '@/components/ui'
import { projectLabel, useProjects } from '@/api/projects'
import { BankTab } from './BankTab'
import { EntriesTab } from './EntriesTab'
import { PartiesTab } from './PartiesTab'
import { ReconcileTab } from './ReconcileTab'
import { ChequesTab } from './ChequesTab'
import { SuppliersTab } from './SuppliersTab'

type Tab = 'parties' | 'entries' | 'bank' | 'reconcile' | 'cheques' | 'suppliers'
const TABS: Tab[] = ['parties', 'entries', 'bank', 'reconcile', 'cheques', 'suppliers']

export default function LedgerPage() {
  // The tab lives in the address, so a link can open one directly.
  const [params, setParams] = useSearchParams()
  const tab = (TABS.find((t) => t === params.get('tab')) ?? 'parties') as Tab
  const setTab = (t: Tab) => setParams((p) => { const n = new URLSearchParams(p); if (t === 'parties') n.delete('tab'); else n.set('tab', t); return n }, { replace: true })
  // A project chosen on the Finance Dashboard narrows the party ledgers and the vouchers to that project.
  const job = Number(params.get('project')) || 0
  const projects = useProjects()
  const project = (projects.data ?? []).find((p) => p.id === job)
  const clearProject = () => setParams((p) => { const n = new URLSearchParams(p); n.delete('project'); return n }, { replace: true })
  // Payment requests have their own page now; old links and notifications still land on it.
  if (params.get('tab') === 'requests') return <Navigate to="/money/approvals" replace />
  return (
    <>
      <PageHeader eyebrow="Accounts" title="Ledgers & Bank" description="Receipts, payments, party ledgers, the bank book and the supplier master. Paying a bill is always the same three fields, wherever it is opened from." />
      <div className="mb-5">
        <Tabs label="View" value={tab} onChange={setTab} items={[{ value: 'parties', label: 'Parties' }, { value: 'entries', label: 'Receipts & payments' }, { value: 'bank', label: 'Bank book' }, { value: 'reconcile', label: 'Reconciliation' }, { value: 'cheques', label: 'Cheques' }, { value: 'suppliers', label: 'Suppliers' }]} />
      </div>
      {job > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/40 p-3 text-sm" role="status">
          <span>Showing the ledgers of <strong>{project ? projectLabel(project) : `project ${job}`}</strong> only.</span>
          <Button size="sm" variant="outline" onClick={clearProject}>Show every project</Button>
        </div>
      )}
      {tab === 'parties' && <PartiesTab job={job} />}
      {tab === 'entries' && <EntriesTab job={job} />}
      {tab === 'bank' && <BankTab />}
      {tab === 'reconcile' && <ReconcileTab />}
      {tab === 'cheques' && <ChequesTab />}
      {tab === 'suppliers' && <SuppliersTab />}
    </>
  )
}
