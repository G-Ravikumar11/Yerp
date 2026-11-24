import { lazy, Suspense, useState } from 'react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Skeleton, Tabs } from '@/components/ui'
import { useSession } from '@/lib/session'

const CompanyTab = lazy(() => import('./CompanyTab'))
const DocumentsTab = lazy(() => import('./DocumentsTab'))
const ApprovalsTab = lazy(() => import('./ApprovalsTab'))
const AccessTab = lazy(() => import('./AccessTab'))
const DataTab = lazy(() => import('./DataTab'))
const ErrorLogTab = lazy(() => import('./ErrorLogTab'))
const WebsiteTab = lazy(() => import('./WebsiteTab'))

const TABS = [
  { value: 'company', label: 'Company' },
  { value: 'documents', label: 'Documents' },
  { value: 'approvals', label: 'Approvals' },
  { value: 'access', label: 'People & access' },
  { value: 'website', label: 'Website' },
  { value: 'data', label: 'Alerts & data' },
  { value: 'errors', label: 'Error log' },
] as const
type Tab = (typeof TABS)[number]['value']

/** The owner's settings: company, paper, approval rules, who can sign in, the website, alerts and backups.
 *  Staff never see the Master's tabs; one who has been given "Manage website" sees the Website tab and nothing else. */
export default function SettingsPage() {
  const { user, can } = useSession()
  const staff = user?.type === 'employee'
  const tabs = TABS.filter((t) => (t.value === 'website' ? can('website.manage') : !staff))
  // Back from connecting Gmail: open the tab its section is on, so its message is seen.
  const [chosen, setTab] = useState<Tab>(() => { const q = new URLSearchParams(window.location.search); return q.get('gmail') ? 'data' : q.get('tab') === 'website' ? 'website' : 'company' })
  const tab = tabs.some((t) => t.value === chosen) ? chosen : tabs[0]?.value
  if (!user) return <Skeleton className="h-96 w-full" />
  if (!tab) return <p className="text-sm text-muted-foreground">Settings are kept by the Master.</p>
  return (
    <>
      <PageHeader eyebrow={staff ? 'Website' : 'Master'} title="Settings" description={staff ? 'The company website: its words and pictures, drafted and published.' : 'The company on paper, who signs what, who can sign in, the website, and where alerts go.'} />
      {tabs.length > 1 && <div className="mb-6"><Tabs label="Settings sections" value={tab} onChange={setTab} items={tabs} /></div>}
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        {tab === 'company' && <CompanyTab />}
        {tab === 'documents' && <DocumentsTab />}
        {tab === 'approvals' && <ApprovalsTab />}
        {tab === 'access' && <AccessTab />}
        {tab === 'website' && <WebsiteTab />}
        {tab === 'data' && <DataTab />}
        {tab === 'errors' && <ErrorLogTab />}
      </Suspense>
    </>
  )
}
