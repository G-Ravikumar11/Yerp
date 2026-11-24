import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Tabs } from '@/components/ui'
import { AnalyticsTab } from './AnalyticsTab'
import { BiometricTab } from './BiometricTab'
import { HistoryTab } from './HistoryTab'
import { JobLockTab } from './JobLockTab'
import { OvertimeTab } from './OvertimeTab'
import { SettingsTab } from './SettingsTab'
import { TodayTab } from './TodayTab'

type Tab = 'today' | 'history' | 'analytics' | 'overtime' | 'joblock' | 'biometric' | 'settings'
const TABS = [
  { value: 'today', label: 'Today' },
  { value: 'history', label: 'History' },
  { value: 'analytics', label: 'Analytics' },
  { value: 'overtime', label: 'Overtime' },
  { value: 'joblock', label: 'Site Lock' },
  { value: 'biometric', label: 'Biometric' },
  { value: 'settings', label: 'Settings' },
] as const

export default function AttendancePage() {
  // ?tab=biometric (from the setup check, say) opens on that tab.
  const [params] = useSearchParams()
  const [tab, setTab] = useState<Tab>(() => (TABS.some((t) => t.value === params.get('tab')) ? (params.get('tab') as Tab) : 'today'))
  return (
    <>
      <PageHeader eyebrow="People" title="Attendance" description="Who is in today, the record of every day, overtime, and the rules that decide who counts as late." />
      <div className="mb-6"><Tabs label="Attendance" items={TABS} value={tab} onChange={setTab} /></div>
      {tab === 'today' && <TodayTab />}
      {tab === 'history' && <HistoryTab />}
      {tab === 'analytics' && <AnalyticsTab />}
      {tab === 'overtime' && <OvertimeTab />}
      {tab === 'joblock' && <JobLockTab />}
      {tab === 'biometric' && <BiometricTab />}
      {tab === 'settings' && <SettingsTab />}
    </>
  )
}
