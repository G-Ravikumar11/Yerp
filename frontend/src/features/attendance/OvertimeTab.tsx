import { useState } from 'react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Field, Input, NumField, Select } from '@/components/ui'
import { announceOvertime, attKeys, useOvertime, type OvertimeLog } from '@/api/attendance'
import { useEmployees } from '@/api/people'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'

/** Announce overtime to somebody, and the log of what has been announced. */
export function OvertimeTab() {
  const logs = useOvertime()
  const people = useEmployees('')
  const [who, setWho] = useState('')
  const [date, setDate] = useState(today())
  const [hours, setHours] = useState(1)
  const [reason, setReason] = useState('')
  const send = useAction(() => announceOvertime({ employee_id: Number(who), date, hours, reason }), { invalidate: [attKeys.all], success: (r) => r.message, onSuccess: () => setReason('') })
  const columns: TableColumn<OvertimeLog>[] = [
    { id: 'who', header: 'Employee', cell: (l) => <span className="font-medium">{l.employee_name}</span> },
    { id: 'date', header: 'Date', sort: (l) => l.date, cell: (l) => formatDate(l.date) },
    { id: 'hours', header: 'Hours', align: 'right', cell: (l) => `${l.hours}h` },
    { id: 'reason', header: 'Reason', hideBelow: 'md', cell: (l) => l.reason || '-' },
    { id: 'by', header: 'Announced by', hideBelow: 'lg', cell: (l) => l.announced_by || '-' },
    { id: 'status', header: 'Status', cell: (l) => <Badge>{l.status}</Badge> },
  ]
  return (
    <>
      <section aria-label="Announce overtime" className="mb-6 max-w-3xl rounded-xl border border-border bg-card p-4 shadow-card">
        <h2 className="mb-3 text-sm font-semibold">Announce overtime</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Employee" htmlFor="ot-who"><Select id="ot-who" value={who} placeholder="Choose an employee" onChange={(e) => setWho(e.target.value)} options={(people.data ?? []).map((e) => ({ value: e.id, label: e.full_name || `${e.first_name} ${e.last_name}` }))} /></Field>
          <Field label="Date" htmlFor="ot-date"><Input id="ot-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
          <Field label="Hours" htmlFor="ot-hours"><NumField id="ot-hours" value={hours} onValue={setHours} /></Field>
          <Field label="Reason" htmlFor="ot-reason"><Input id="ot-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Deadline, client meeting..." /></Field>
        </div>
        <div className="mt-4 flex items-center justify-end gap-3">
          {send.error && <p role="alert" className="mr-auto text-[13px] text-danger">{send.error.message}</p>}
          <Button loading={send.isPending} disabled={!who || !(hours > 0)} onClick={() => send.mutate()}>Announce overtime</Button>
        </div>
      </section>
      <DataTable label="Overtime log" rows={logs.data ?? []} columns={columns} rowKey={(l, i) => l.id ?? i} loading={logs.isPending} empty="No overtime announced yet." />
    </>
  )
}
