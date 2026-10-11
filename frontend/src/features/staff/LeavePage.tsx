import { useState } from 'react'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Field, Input, Modal, Select, Stat, StatGrid, Textarea } from '@/components/ui'
import { requestLeave, staffKeys, useMyLeave, type LeaveRequest } from '@/api/staff'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'

const TYPES = [
  { value: 'annual', label: 'Annual leave' },
  { value: 'sick', label: 'Sick leave' },
  { value: 'personal', label: 'Personal leave' },
  { value: 'unpaid', label: 'Unpaid leave' },
]
const tone = (s: string) => (s === 'approved' ? 'success' : s === 'rejected' ? 'danger' : 'warning') as 'success' | 'danger' | 'warning'

/** The person's leave: what they have left, what they have asked for, and a way to ask. */
export default function LeavePage() {
  const q = useMyLeave()
  const [asking, setAsking] = useState(false)
  const b = q.data?.balance
  const columns: TableColumn<LeaveRequest>[] = [
    { id: 'type', header: 'Type', cell: (l) => `${l.leave_type.charAt(0).toUpperCase()}${l.leave_type.slice(1)} leave` },
    { id: 'from', header: 'From', sort: (l) => l.start_date, cell: (l) => formatDate(l.start_date) },
    { id: 'to', header: 'To', cell: (l) => formatDate(l.end_date) },
    { id: 'days', header: 'Days', align: 'right', cell: (l) => l.days },
    { id: 'reason', header: 'Reason', hideBelow: 'lg', cell: (l) => l.reason || '-' },
    { id: 'status', header: 'Status', cell: (l) => <Badge tone={tone(l.status)} dot>{l.status.charAt(0).toUpperCase() + l.status.slice(1)}</Badge> },
  ]
  return (
    <>
      <PageHeader eyebrow="My work" title="My Leave" description="Days are counted as working days, and checked against what you have left." actions={<Button onClick={() => setAsking(true)}><Plus /> Ask for leave</Button>} />
      <StatGrid>
        <Stat label="Annual leave left" value={b ? b.annual_remaining : 0} sub={b ? `of ${b.annual_total} (${b.annual_pending} waiting for approval)` : undefined} loading={q.isPending} />
        <Stat label="Annual taken" value={b?.annual_taken ?? 0} loading={q.isPending} />
        <Stat label="Sick leave left" value={b ? b.sick_remaining : 0} sub={b ? `of ${b.sick_total}` : undefined} loading={q.isPending} />
        <Stat label="Sick taken" value={b?.sick_taken ?? 0} loading={q.isPending} />
      </StatGrid>
      <DataTable label="Leave requests" rows={q.data?.requests ?? []} columns={columns} rowKey={(l) => l.id} loading={q.isPending} empty="No leave requested yet." />
      <Modal open={asking} onOpenChange={setAsking} title="Ask for leave" description="Your manager is asked to approve it.">
        {asking && <Form onClose={() => setAsking(false)} />}
      </Modal>
    </>
  )
}

function Form({ onClose }: { onClose: () => void }) {
  const [type, setType] = useState('annual')
  const [from, setFrom] = useState(today())
  const [to, setTo] = useState(today())
  const [reason, setReason] = useState('')
  const save = useAction(() => requestLeave({ leave_type: type, start_date: from, end_date: to, reason }), { invalidate: [staffKeys.all], success: (r) => r.message || 'Leave requested', onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Kind of leave" htmlFor="lv-type" className="sm:col-span-2"><Select id="lv-type" value={type} onChange={(e) => setType(e.target.value)} options={TYPES} /></Field>
        <Field label="From" htmlFor="lv-from"><Input id="lv-from" type="date" value={from} onChange={(e) => { setFrom(e.target.value); if (e.target.value > to) setTo(e.target.value) }} /></Field>
        <Field label="To" htmlFor="lv-to"><Input id="lv-to" type="date" min={from} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        <Field label="Reason" htmlFor="lv-reason" className="sm:col-span-2"><Textarea id="lv-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!from || !to} onClick={() => save.mutate()}>Send request</Button>
      </div>
    </div>
  )
}
