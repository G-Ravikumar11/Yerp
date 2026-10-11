import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Stat, StatGrid } from '@/components/ui'
import { useMyDashboard, type Attendance } from '@/api/staff'
import { formatDate } from '@/lib/format'

const hours = (n: number | undefined) => (n && n > 0 ? n.toFixed(2) : '-')

/** The last thirty days of the person's own clock. */
export default function TimesheetPage() {
  const q = useMyDashboard()
  const s = q.data?.attendance_summary
  const columns: TableColumn<Attendance>[] = [
    { id: 'date', header: 'Date', sort: (a) => a.date, cell: (a) => formatDate(a.date) },
    { id: 'in', header: 'In', cell: (a) => a.clock_in?.slice(0, 5) || '-' },
    { id: 'out', header: 'Out', cell: (a) => a.clock_out?.slice(0, 5) || '-' },
    { id: 'break', header: 'Break', hideBelow: 'md', align: 'right', cell: (a) => (a.break_minutes ? `${a.break_minutes} min` : '-') },
    { id: 'hours', header: 'Hours', align: 'right', sort: (a) => a.total_hours ?? 0, cell: (a) => hours(a.total_hours) },
    { id: 'ot', header: 'Overtime', hideBelow: 'md', align: 'right', cell: (a) => hours(a.overtime_hours) },
    { id: 'where', header: 'Where', hideBelow: 'lg', cell: (a) => (a.check_type ? a.check_type.charAt(0).toUpperCase() + a.check_type.slice(1) : '-') },
    { id: 'status', header: 'Status', cell: (a) => <Badge tone={a.status === 'late' ? 'warning' : a.status === 'absent' ? 'danger' : 'success'}>{a.status ? a.status.charAt(0).toUpperCase() + a.status.slice(1) : '-'}</Badge> },
  ]
  return (
    <>
      <PageHeader eyebrow="My work" title="Timesheet" description="Your clock in and out for the last thirty days." />
      <StatGrid>
        <Stat label="Days present" value={s?.days_present ?? 0} loading={q.isPending} />
        <Stat label="Hours worked" value={s?.total_hours ?? 0} loading={q.isPending} />
        <Stat label="Average a day" value={s?.avg_hours ?? 0} sub="hours" loading={q.isPending} />
      </StatGrid>
      <DataTable label="Timesheet" rows={q.data?.attendance ?? []} columns={columns} rowKey={(a) => a.date} loading={q.isPending} empty="No days recorded yet. Clock in from My work and they appear here." />
    </>
  )
}
