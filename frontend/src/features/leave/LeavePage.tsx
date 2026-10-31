import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Field, NumField, Stat, StatGrid, Tabs } from '@/components/ui'
import { decideLeave, leaveKeys, useLeaveRequests, type LeaveRow } from '@/api/leave'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import { payKeys, setLeaveAccrual, useLeaveAccrual } from '@/api/payroll'
import { useSession } from '@/lib/session'

type Filter = 'all' | 'pending' | 'approved' | 'rejected'
const tone = (s: string) => (s === 'approved' ? 'success' : s === 'rejected' ? 'danger' : 'warning') as 'success' | 'danger' | 'warning'

/** Everybody's leave requests: decide the pending ones, see who is away today. */
/** Whether leave is earned month by month, and how much of it carries into the next year. HR and the Master change it. */
function LeaveAccrual() {
  const { isHrOrMaster } = useSession()
  const q = useLeaveAccrual(isHrOrMaster)             // only HR may read it: no request for anybody else
  const [carry, setCarry] = useState<{ annual: number; sick: number } | null>(null)
  const limits = carry ?? q.data?.carry_max ?? { annual: 30, sick: 0 }
  const save = useAction((b: Parameters<typeof setLeaveAccrual>[0]) => setLeaveAccrual(b), {
    invalidate: [payKeys.all, ['people'], ['leave']], success: (r) => (r.credited ? `${r.message}. ${r.credited} month(s) of leave credited.` : r.message || 'Saved'), onSuccess: () => setCarry(null),
  })
  if (!isHrOrMaster || !q.data) return null
  const on = q.data.enabled
  return (
    <section aria-label="Leave accrual" className="mb-4 rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">Monthly leave accrual</p>
          <p className="text-[13px] text-muted-foreground">{on ? "On. A twelfth of each year's entitlement is credited on the 1st of every month; unused leave carries over up to the limits below and the rest lapses on 1 January." : "Off. Everybody has their whole year's leave from 1 January. Turning it on credits the months of this year already begun."}</p>
        </div>
        <button type="button" role="switch" aria-checked={on} aria-label="Monthly leave accrual" disabled={save.isPending} onClick={() => save.mutate({ enabled: !on })}
          className={'relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 ' + (on ? 'bg-[var(--primary)]' : 'bg-muted-foreground/30')}>
          <span className={'absolute top-0.5 size-4 rounded-full bg-white transition-all ' + (on ? 'left-[18px]' : 'left-0.5')} />
        </button>
      </div>
      {on && (
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <Field label="Annual days carried over" htmlFor="la-annual"><NumField id="la-annual" value={limits.annual} onValue={(n) => setCarry({ ...limits, annual: n })} /></Field>
          <Field label="Sick days carried over" htmlFor="la-sick"><NumField id="la-sick" value={limits.sick} onValue={(n) => setCarry({ ...limits, sick: n })} /></Field>
          {carry && <Button size="sm" loading={save.isPending} onClick={() => save.mutate({ carry_max: carry })}>Save limits</Button>}
        </div>
      )}
    </section>
  )
}

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
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (l) => <MasterDelete kind="leave" id={l.id} label={`${l.employee_name} from ${formatDate(l.start_date)}`} noun="leave request" /> },
  ]
  return (
    <>
      <PageHeader eyebrow="People" title="Leave" description="Review and decide leave requests. Approving is checked against what the person has left." />
      <LeaveAccrual />
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
