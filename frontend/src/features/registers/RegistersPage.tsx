import { useState } from 'react'
import { Download } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button, Tabs } from '@/components/ui'
import { GuaranteesTab } from './GuaranteesTab'
import { TdsTab } from './TdsTab'

type Tab = 'tds' | 'guarantees'
const EXCEL: Record<Tab, string> = { tds: '/api/registers/tds.xlsx', guarantees: '/api/registers/guarantees.xlsx' }

export default function RegistersPage() {
  const [tab, setTab] = useState<Tab>('tds')
  return (
    <>
      <PageHeader
        eyebrow="Accounts"
        title="TDS & Guarantees"
        description="The sheets the accountant kept by hand: TDS by quarter, and guarantees and when they lapse. Advances have their own page."
        actions={<Button variant="outline" asChild><a href={EXCEL[tab]}><Download /> Excel</a></Button>}
      />
      <div className="mb-5"><Tabs label="Register" value={tab} onChange={setTab} items={[{ value: 'tds', label: 'TDS (194C)' }, { value: 'guarantees', label: 'Guarantees' }]} /></div>
      {tab === 'tds' && <TdsTab />}
      {tab === 'guarantees' && <GuaranteesTab />}
    </>
  )
}
