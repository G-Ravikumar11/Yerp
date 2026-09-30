import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Stat, StatGrid, Tabs } from '@/components/ui'
import { decideLeave, leaveKeys, useLeaveRequests, type LeaveRow } from '@/api/leave'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'

type Filter = 'all' | 'pending' | 'approved' | 'rejected'
const tone = (s: string) => (s === 'approved' ? 'success' : s === 'rejected' ? 'danger' : 'warning') as 'success' | 'danger' | 'warning'

/** Everybody's leave requests: decide the pending ones, see who is away today. */
export default function LeavePage() {
  const q = useLeaveRequests()
  const [filter, setFilter] = useState<Filter>('all')
  const [deciding, setDeciding] = useState<{ row: LeaveRow; action: 'approve' | 'reject' } | null>(null)
  const decide = useAction((v: { row: LeaveRow; action: 'approve' | 'reject' }) => decideLeave(v.row.id, v.action), { invalidate: [leaveKeys.all, ['approvals']], success: (r) => r.message || 'Done', onSuccess: () => setDeciding(null) })
  const all = q.data ?? []
  const t = today()
  const count = (s: string) => all.filter((l) => l.status === s).length
  const away = all.filter((l) => l.status === 'approved' && l.start_date <= t && t <= l.end_date).length
  const rows = filter === 'all' ? all : all.filter((l) => l.status === filter)
  const columns: TableColumn<LeaveRow>[] = [
    { id: 'who', header: 'Employee', sort: (l) => l.employee_name, cell: (l) => <Link className="font-medium text-primary underline-offset-2 hover:underline" to={`/people/employees/${l.employee_id}`}>{l.employee_name || '-'}</Link> },
    { id: 'type', header: 'Type', cell: (l) => `${l.leave_type.charAt(0).toUpperCase()}${l.leave_type.slice(1)}` },
    { id: 'from', header: 'From', sort: (l) => l.start_date, cell: (l) => formatDate(l.start_date) },
    { id: 'to', header: 'To', hideBelow: 'md', cell: (l) => formatDate(l.end_date) },
    { id: 'days', header: 'Days', align: 'right', cell: (l) => <strong>{l.days}</strong> },
    { id: 'reason', header: 'Reason', hideBelow: 'lg', cell: (l) => <span className="block max-w-56 truncate" title={l.reason}>{l.reason || '-'}</span> },
    { id: 'status', header: 'Status', cell: (l) => <Badge tone={tone(l.status)} dot>{l.status.charAt(0).toUpperCase() + l.status.slice(1)}</Badge> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (l) => l.status === 'pending' ? (
        <div className="flex justify-end gap-1.5"><Button size="sm" onClick={() => setDeciding({ row: l, action: 'approve' })}>Approve</Button><Button size="sm" variant="outline" className="text-danger" onClick={() => setDeciding({ row: l, action: 'reject' })}>Reject</Button></div>
      ) : <span className="text-xs text-muted-foreground">{l.approved_by}</span>,
    },
  ]
  return (
    <>
      <PageHeader eyebrow="People" title="Leave" description="Review and decide leave requests. Approving is checked against what the person has left." />
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Waiting for a decision" value={count('pending')} tone={count('pending') ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Approved" value={count('approved')} loading={q.isPending} />
        <Stat label="Away today" value={away} loading={q.isPending} />
        <Stat label="Rejected" value={count('rejected')} loading={q.isPending} />
      </StatGrid>
      <div className="mb-4"><Tabs label="Leave status" value={filter} onChange={setFilter} items={[{ value: 'all', label: 'All', count: all.length }, { value: 'pending', label: 'Pending', count: count('pending') }, { value: 'approved', label: 'Approved' }, { value: 'rejected', label: 'Rejected' }]} /></div>
      <DataTable label="Leave requests" rows={rows} columns={columns} rowKey={(l) => l.id} loading={q.isPending} empty="No leave requests found." />
      <ConfirmDialog
        open={!!deciding}
        onOpenChange={(o) => !o && setDeciding(null)}
        title={deciding ? `${deciding.action === 'approve' ? 'Approve' : 'Reject'} leave for ${deciding.row.employee_name}?` : ''}
        description={deciding ? `${deciding.row.days} day(s) of ${deciding.row.leave_type} leave, ${formatDate(deciding.row.start_date)} to ${formatDate(deciding.row.end_date)}. They are told of the decision.` : undefined}
        confirmLabel={deciding?.action === 'approve' ? 'Approve' : 'Reject'}
        tone={deciding?.action === 'reject' ? 'danger' : undefined}
        loading={decide.isPending}
        onConfirm={() => { if (deciding) decide.mutate(deciding) }}
      />
    </>
  )
}
