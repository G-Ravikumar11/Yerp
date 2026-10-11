import { useState } from 'react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Tabs } from '@/components/ui'
import { BankTab } from './BankTab'
import { EntriesTab } from './EntriesTab'
import { PartiesTab } from './PartiesTab'
import { SuppliersTab } from './SuppliersTab'

type Tab = 'parties' | 'entries' | 'bank' | 'suppliers'

export default function LedgerPage() {
  const [tab, setTab] = useState<Tab>('parties')
  return (
    <>
      <PageHeader eyebrow="Money" title="Payments & Ledgers" description="Receipts, payments, party ledgers, the bank book and the supplier master. Paying a bill is always the same three fields, wherever it is opened from." />
      <div className="mb-5">
        <Tabs label="View" value={tab} onChange={setTab} items={[{ value: 'parties', label: 'Parties' }, { value: 'entries', label: 'Receipts & payments' }, { value: 'bank', label: 'Bank book' }, { value: 'suppliers', label: 'Suppliers' }]} />
      </div>
      {tab === 'parties' && <PartiesTab />}
      {tab === 'entries' && <EntriesTab />}
      {tab === 'bank' && <BankTab />}
      {tab === 'suppliers' && <SuppliersTab />}
    </>
  )
}
