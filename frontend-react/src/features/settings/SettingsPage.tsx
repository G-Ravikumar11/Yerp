import { lazy, Suspense, useState } from 'react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Skeleton, Tabs } from '@/components/ui'

const CompanyTab = lazy(() => import('./CompanyTab'))
const DocumentsTab = lazy(() => import('./DocumentsTab'))
const ApprovalsTab = lazy(() => import('./ApprovalsTab'))
const AccessTab = lazy(() => import('./AccessTab'))
const DataTab = lazy(() => import('./DataTab'))

const TABS = [
  { value: 'company', label: 'Company' },
  { value: 'documents', label: 'Documents' },
  { value: 'approvals', label: 'Approvals' },
  { value: 'access', label: 'People & access' },
  { value: 'data', label: 'Alerts & data' },
] as const
type Tab = (typeof TABS)[number]['value']

/** The owner's settings: company, paper, approval rules, who can sign in, alerts and backups. */
export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>('company')
  return (
    <>
      <PageHeader eyebrow="Master" title="Settings" description="The company on paper, who signs what, who can sign in, and where alerts go." />
      <div className="mb-6"><Tabs label="Settings sections" value={tab} onChange={setTab} items={TABS} /></div>
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        {tab === 'company' && <CompanyTab />}
        {tab === 'documents' && <DocumentsTab />}
        {tab === 'approvals' && <ApprovalsTab />}
        {tab === 'access' && <AccessTab />}
        {tab === 'data' && <DataTab />}
      </Suspense>
    </>
  )
}
