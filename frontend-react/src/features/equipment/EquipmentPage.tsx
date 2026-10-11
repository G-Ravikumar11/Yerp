import { useState } from 'react'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Select, Stat, StatGrid } from '@/components/ui'
import { backInService, eqKeys, useRegister, type Machine } from '@/api/equipment'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'
import { LogModal } from './LogModal'
import { MachineDetail } from './MachineDetail'
import { MachineModal } from './MachineModal'
import { MoveModal } from './MoveModal'
import { ServiceModal } from './ServiceModal'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

const tone = (s: string) => (s === 'Deployed' ? 'success' : s === 'Under repair' ? 'danger' : 'neutral') as 'success' | 'danger' | 'neutral'

/** Where each machine is, what it did, what it burned and when it is due - and what it cost the site it worked for. */
export default function EquipmentPage() {
  const { can } = useSession()
  const [status, setStatus] = useState('')
  const q = useRegister(status)
  const [editing, setEditing] = useState<Machine | 'new' | null>(null)
  const [moving, setMoving] = useState<Machine | null>(null)
  const [logging, setLogging] = useState<Machine | null>(null)
  const [servicing, setServicing] = useState<Machine | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const back = useAction((m: Machine) => backInService(m.id), { invalidate: [eqKeys.all], success: (r) => r.message })
  const s = q.data?.summary
  const manage = can('stores.manage|workorders.manage')
  const columns: TableColumn<Machine>[] = [
    { id: 'code', header: 'Code', sort: (m) => m.code, cell: (m) => <span className="font-mono text-[13px] font-semibold">{m.code}</span> },
    { id: 'name', header: 'Machine', sort: (m) => m.name, cell: (m) => <div><button type="button" className="font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setOpen(m.id)}>{m.name}</button><div className="text-xs text-muted-foreground">{m.category}{m.reg_no && ` - ${m.reg_no}`} - {m.ownership}{m.ownership === 'Hired' && ` at ${formatINR(m.hire_rate)}/${m.hire_basis.toLowerCase()}`}</div></div> },
    { id: 'status', header: 'Status', cell: (m) => <Badge tone={tone(m.status)} dot>{m.status}</Badge> },
    { id: 'where', header: 'Where', hideBelow: 'md', cell: (m) => m.current_job || 'Yard' },
    { id: 'meter', header: 'Meter', hideBelow: 'lg', align: 'right', cell: (m) => <div>{m.meter_reading.toLocaleString('en-IN')} {m.meter_unit.toLowerCase()}{m.service.reasons.length > 0 && <div className={`text-xs ${m.service.due ? 'font-semibold text-danger' : 'text-warning'}`}>{m.service.reasons.join('; ')}</div>}</div> },
    { id: 'cost', header: 'Cost to date', hideBelow: 'md', align: 'right', sort: (m) => m.cost_to_date, cell: (m) => formatINR(m.cost_to_date) },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (m) => m.status === 'Disposed' ? null : (
        <div className="flex flex-wrap justify-end gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setMoving(m)}>{m.current_job_id ? 'Move' : 'Deploy'}</Button>
          {m.status === 'Deployed' && <Button size="sm" onClick={() => setLogging(m)}>Log day</Button>}
          {m.status === 'Under repair' ? <Button size="sm" loading={back.isPending && back.variables?.id === m.id} onClick={() => back.mutate(m)}>Back at work</Button> : <Button size="sm" variant="outline" onClick={() => setServicing(m)}>Service</Button>}
          {manage && <Button size="sm" variant="ghost" onClick={() => setEditing(m)}>Edit</Button>}
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="equipment" id={r.id} label={String(r.name)} noun="equipment" /> },
  ]
  const filters = useListFilters(q.data?.assets, {
    search: (m) => [m.code, m.name, m.category, m.make, m.model, m.reg_no, m.current_job, m.hired_from, m.status].join(' '),
    status: (m) => m.status,
    date: (m) => m.purchase_date,
  })
  return (
    <>
      <PageHeader eyebrow="Projects" title="Equipment & Plant" description="Where each machine is, what it did, what it burned and when it is due - and what it cost the site it worked for." actions={<>{manage && <Button onClick={() => setEditing('new')}><Plus /> Machine</Button>}<div className="w-44"><Select aria-label="Status" value={status} placeholder="Every machine" onChange={(e) => setStatus(e.target.value)} options={['Deployed', 'Available', 'Under repair', 'Disposed'].map((x) => ({ value: x, label: x }))} /></div></>} />
      <StatGrid>
        <Stat label="Machines" value={s?.machines ?? 0} loading={q.isPending} />
        <Stat label="On sites" value={s?.deployed ?? 0} loading={q.isPending} />
        <Stat label="Idle in the yard" value={s?.idle_in_yard ?? 0} loading={q.isPending} />
        <Stat label="Service due" value={s?.service_due ?? 0} sub={s?.service_soon ? `+${s.service_soon} soon` : undefined} tone={s?.service_due ? 'danger' : undefined} loading={q.isPending} />
        <Stat label="Cost to date" value={formatINR(s?.cost_to_date ?? 0)} loading={q.isPending} />
      </StatGrid>
      <FilterBar filters={filters} placeholder="Search by code, name, make, registration..." />
      <DataTable label="Machines" rows={filters.filtered} columns={columns} rowKey={(m) => m.id} loading={q.isPending} empty="No machines on the register yet. Add what the business owns, and what it hires in." />
      {open && <MachineDetail id={open} onClose={() => setOpen(null)} />}
      <MachineModal machine={editing && editing !== 'new' ? editing : null} categories={q.data?.categories ?? []} open={!!editing} onClose={() => setEditing(null)} />
      <MoveModal machine={moving} onClose={() => setMoving(null)} />
      <LogModal machine={logging} onClose={() => setLogging(null)} />
      <ServiceModal machine={servicing} onClose={() => setServicing(null)} />
    </>
  )
}
