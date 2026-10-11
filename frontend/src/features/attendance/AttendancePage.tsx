import { useState } from 'react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Tabs } from '@/components/ui'
import { AnalyticsTab } from './AnalyticsTab'
import { HistoryTab } from './HistoryTab'
import { OvertimeTab } from './OvertimeTab'
import { SettingsTab } from './SettingsTab'
import { TodayTab } from './TodayTab'

type Tab = 'today' | 'history' | 'analytics' | 'overtime' | 'settings'
const TABS = [
  { value: 'today', label: 'Today' },
  { value: 'history', label: 'History' },
  { value: 'analytics', label: 'Analytics' },
  { value: 'overtime', label: 'Overtime' },
  { value: 'settings', label: 'Settings' },
] as const

export default function AttendancePage() {
  const [tab, setTab] = useState<Tab>('today')
  return (
    <>
      <PageHeader eyebrow="People" title="Attendance" description="Who is in today, the record of every day, overtime, and the rules that decide who counts as late." />
      <div className="mb-6"><Tabs label="Attendance" items={TABS} value={tab} onChange={setTab} /></div>
      {tab === 'today' && <TodayTab />}
      {tab === 'history' && <HistoryTab />}
      {tab === 'analytics' && <AnalyticsTab />}
      {tab === 'overtime' && <OvertimeTab />}
      {tab === 'settings' && <SettingsTab />}
    </>
  )
}
