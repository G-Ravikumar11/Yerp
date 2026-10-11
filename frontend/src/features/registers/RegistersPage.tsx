import { useState } from 'react'
import { Download } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button, Tabs } from '@/components/ui'
import { AdvancesTab, GuaranteesTab } from './GuaranteesTab'
import { TdsTab } from './TdsTab'

type Tab = 'tds' | 'guarantees' | 'advances'
const EXCEL: Record<Tab, string> = { tds: '/api/registers/tds.xlsx', guarantees: '/api/registers/guarantees.xlsx', advances: '/api/registers/advances.xlsx' }

export default function RegistersPage() {
  const [tab, setTab] = useState<Tab>('tds')
  return (
    <>
      <PageHeader
        eyebrow="Money"
        title="TDS, Guarantees & Advances"
        description="The three sheets the accountant kept by hand: TDS by quarter, guarantees and when they lapse, advances and what has come back."
        actions={<Button variant="outline" asChild><a href={EXCEL[tab]}><Download /> Excel</a></Button>}
      />
      <div className="mb-5"><Tabs label="Register" value={tab} onChange={setTab} items={[{ value: 'tds', label: 'TDS (194C)' }, { value: 'guarantees', label: 'Guarantees' }, { value: 'advances', label: 'Advances' }]} /></div>
      {tab === 'tds' && <TdsTab />}
      {tab === 'guarantees' && <GuaranteesTab />}
      {tab === 'advances' && <AdvancesTab />}
    </>
  )
}
