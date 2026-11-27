import { lazy, Suspense, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Skeleton, Tabs } from '@/components/ui'

const CompanyTab = lazy(() => import('./CompanyTab'))
const DocumentsTab = lazy(() => import('./DocumentsTab'))
const ApprovalsTab = lazy(() => import('./ApprovalsTab'))
const AccessTab = lazy(() => import('./AccessTab'))
const DataTab = lazy(() => import('./DataTab'))
const ErrorLogTab = lazy(() => import('./ErrorLogTab'))

const TABS = [
  { value: 'company', label: 'Company' },
  { value: 'documents', label: 'Documents' },
  { value: 'approvals', label: 'Approvals' },
  { value: 'access', label: 'People & access' },
  { value: 'data', label: 'Alerts & data' },
  { value: 'errors', label: 'Error log' },
] as const
type Tab = (typeof TABS)[number]['value']

/** The owner's settings: company, paper, approval rules, who can sign in, alerts and backups. The company website has a
 *  page of its own (/website); a link to its old place here goes there. */
export default function SettingsPage() {
  const navigate = useNavigate()
  const params = new URLSearchParams(window.location.search)
  const toWebsite = params.get('tab') === 'website'
  useEffect(() => {
    if (toWebsite) {
      params.delete('tab')
      navigate(`/website${params.toString() ? `?${params}` : ''}`, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toWebsite])
  // Back from connecting Gmail: open the tab its section is on, so its message is seen.
  const [tab, setTab] = useState<Tab>(() => (params.get('gmail') ? 'data' : 'company'))
  if (toWebsite) return <Skeleton className="h-96 w-full" />
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
        {tab === 'errors' && <ErrorLogTab />}
      </Suspense>
    </>
  )
}
