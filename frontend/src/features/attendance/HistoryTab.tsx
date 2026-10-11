import { useState } from 'react'
import { Download } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Input } from '@/components/ui'
import { attKeys, clockFor, exportAttendance, useAttRecords, type AttRecord } from '@/api/attendance'
import { useAction } from '@/lib/mutate'
import { toast } from '@/stores/toast'
import { formatDate } from '@/lib/format'

const csv = (rows: Record<string, unknown>[]) => [Object.keys(rows[0]).join(','), ...rows.map((r) => Object.values(r).map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','))].join('\n')

/** The record of clock-ins, for one day or all of them, with a file to take away. */
export function HistoryTab() {
  const [date, setDate] = useState('')
  const q = useAttRecords(date)
  const out = useAction((r: AttRecord) => clockFor(r.employee_id, 'out'), { invalidate: [attKeys.all], success: (r) => r.message })
  const download = async () => {
    const rows = await exportAttendance(date)
    if (!rows.length) return toast.info('No records to export')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csv(rows)], { type: 'text/csv' }))
    a.download = `attendance-${date || 'all'}.csv`
    a.click()
    toast.success(`Exported ${rows.length} records`)
  }
  const columns: TableColumn<AttRecord>[] = [
    { id: 'who', header: 'Employee', sort: (r) => r.employee_name, cell: (r) => <div><span className="font-medium">{r.employee_name}</span><div className="text-xs text-muted-foreground">{r.employee_email}</div></div> },
    { id: 'date', header: 'Date', sort: (r) => r.date, cell: (r) => formatDate(r.date) },
    { id: 'in', header: 'In', cell: (r) => r.clock_in?.slice(0, 5) || '-' },
    { id: 'out', header: 'Out', cell: (r) => r.clock_out?.slice(0, 5) || '-' },
    { id: 'hours', header: 'Hours', align: 'right', sort: (r) => r.total_hours ?? 0, cell: (r) => (r.total_hours ? `${r.total_hours}h` : '-') },
    { id: 'type', header: 'Type', hideBelow: 'lg', cell: (r) => (r.check_type ? <Badge tone={r.check_type === 'office' ? 'info' : 'neutral'}>{r.check_type}</Badge> : '-') },
    { id: 'status', header: 'Status', cell: (r) => <Badge tone={r.status === 'completed' ? 'success' : r.status === 'present' ? 'info' : 'neutral'} dot>{r.status}</Badge> },
    { id: 'act', header: '', align: 'right', cell: (r) => (!r.clock_out && r.clock_in ? <Button size="sm" variant="outline" loading={out.isPending && out.variables?.id === r.id} onClick={() => out.mutate(r)}>Clock out</Button> : null) },
  ]
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label htmlFor="att-date" className="text-sm font-medium">Day</label>
        <div className="w-44"><Input id="att-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
        {date && <Button variant="ghost" size="sm" onClick={() => setDate('')}>All days</Button>}
        <Button variant="outline" className="ml-auto" onClick={() => void download()}><Download /> Export</Button>
      </div>
      <DataTable label="Attendance" rows={q.data ?? []} columns={columns} rowKey={(r) => r.id} loading={q.isPending} empty="No attendance records found." footer={<p className="px-4 py-2 text-xs text-muted-foreground">{q.data?.length ?? 0} records</p>} />
    </>
  )
}
