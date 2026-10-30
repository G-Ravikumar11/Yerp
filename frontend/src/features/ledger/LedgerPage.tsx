import { useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Tabs } from '@/components/ui'
import { BankTab } from './BankTab'
import { EntriesTab } from './EntriesTab'
import { PartiesTab } from './PartiesTab'
import { RequestsTab } from './RequestsTab'
import { ReconcileTab } from './ReconcileTab'
import { ChequesTab } from './ChequesTab'
import { SuppliersTab } from './SuppliersTab'

type Tab = 'parties' | 'entries' | 'requests' | 'bank' | 'reconcile' | 'cheques' | 'suppliers'
const TABS: Tab[] = ['parties', 'entries', 'requests', 'bank', 'reconcile', 'cheques', 'suppliers']

export default function LedgerPage() {
  // The tab lives in the address, so the Approvals inbox can open Payment requests directly.
  const [params, setParams] = useSearchParams()
  const tab = (TABS.find((t) => t === params.get('tab')) ?? 'parties') as Tab
  const setTab = (t: Tab) => setParams((p) => { const n = new URLSearchParams(p); if (t === 'parties') n.delete('tab'); else n.set('tab', t); return n }, { replace: true })
  return (
    <>
      <PageHeader eyebrow="Accounts" title="Payments & Ledgers" description="Receipts, payments, party ledgers, the bank book and the supplier master. Paying a bill is always the same three fields, wherever it is opened from." />
      <div className="mb-5">
        <Tabs label="View" value={tab} onChange={setTab} items={[{ value: 'parties', label: 'Parties' }, { value: 'entries', label: 'Receipts & payments' }, { value: 'requests', label: 'Payment requests' }, { value: 'bank', label: 'Bank book' }, { value: 'reconcile', label: 'Reconciliation' }, { value: 'cheques', label: 'Cheques' }, { value: 'suppliers', label: 'Suppliers' }]} />
      </div>
      {tab === 'parties' && <PartiesTab />}
      {tab === 'entries' && <EntriesTab />}
      {tab === 'requests' && <RequestsTab />}
      {tab === 'bank' && <BankTab />}
      {tab === 'reconcile' && <ReconcileTab />}
      {tab === 'cheques' && <ChequesTab />}
      {tab === 'suppliers' && <SuppliersTab />}
    </>
  )
}
