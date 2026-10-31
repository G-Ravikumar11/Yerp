import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Archive, Image, Plus, RotateCcw } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilesModal } from '@/components/data/FilesModal'
import { Button, Card, ConfirmDialog, Select, Tabs } from '@/components/ui'
import { archiveMachine, backInService, eqKeys, useRegister, type Machine } from '@/api/equipment'
import { STATUS_LABEL } from '@/api/plant'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'
import { MachineDetail } from './MachineDetail'
import { MachineModal } from './MachineModal'
import { MoveModal } from './MoveModal'
import { ServiceModal } from './ServiceModal'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import { PlantDashboard } from './PlantDashboard'
import { Allocations, Logbook } from './PlantPeople'
import { Fuel, Maintenance } from './PlantFuelMaint'
import { Expenses, Rentals } from './PlantRentals'
import { PlantAlerts } from './PlantChecks'
import { FormworkHire } from './PlantFormwork'
import { PlantReports } from './PlantReports'
import { ServiceBadge, StatusBadge, usePaged } from './plantParts'
import { ServiceDoneModal } from './ServiceDoneModal'
import { formatDate } from '@/lib/format'

const SERVICE_ORDER = ['Overdue', 'Service due', 'Due soon', 'Upcoming', 'Incomplete', 'Not scheduled']

type Tab = 'dashboard' | 'register' | 'allocation' | 'logbook' | 'fuel' | 'maintenance' | 'rentals' | 'expenses' | 'formwork' | 'alerts' | 'reports'
const TABS: { value: Tab; label: string }[] = [
  { value: 'dashboard', label: 'Dashboard' }, { value: 'register', label: 'Register' }, { value: 'allocation', label: 'Allocation' }, { value: 'logbook', label: 'Logbook' },
  { value: 'fuel', label: 'Fuel' }, { value: 'maintenance', label: 'Maintenance' }, { value: 'rentals', label: 'Rentals' }, { value: 'expenses', label: 'Expenses' }, { value: 'formwork', label: 'Shuttering & Scaffolding' }, { value: 'alerts', label: 'Alerts' }, { value: 'reports', label: 'Reports' },
]

/** Where each machine is, who works it, what it did, what it burned and when it is due - and what it costs. */
export default function EquipmentPage() {
  // The tab is in the address, so a link (or a reload) opens the same one.
  const [params, setParams] = useSearchParams()
  const tab = (TABS.some((t) => t.value === params.get('tab')) ? params.get('tab') : 'dashboard') as Tab
  const setTab = (t: Tab) => setParams(t === 'dashboard' ? {} : { tab: t }, { replace: true })
  return (
    <>
      <PageHeader eyebrow="Projects" title="Equipment & Plant" description="Where each machine is, who works it, what it did, what it burned and when it is due - and what it costs." />
      <div className="mb-5 overflow-x-auto"><Tabs label="Equipment & Plant" value={tab} onChange={setTab} items={TABS} /></div>
      {tab === 'dashboard' && <PlantDashboard onGo={(t) => setTab(t as Tab)} />}
      {tab === 'register' && <Register />}
      {tab === 'allocation' && <Allocations />}
      {tab === 'logbook' && <Logbook />}
      {tab === 'fuel' && <Fuel />}
      {tab === 'maintenance' && <Maintenance />}
      {tab === 'rentals' && <Rentals />}
      {tab === 'expenses' && <Expenses />}
      {tab === 'formwork' && <FormworkHire />}
      {tab === 'alerts' && <PlantAlerts />}
      {tab === 'reports' && <PlantReports />}
    </>
  )
}

function Register() {
  const { can } = useSession()
  const [status, setStatus] = useState('')
  const [archived, setArchived] = useState(false)
  const q = useRegister(status, archived)
  const [editing, setEditing] = useState<Machine | 'new' | null>(null)
  const [moving, setMoving] = useState<Machine | null>(null)
  const [servicing, setServicing] = useState<Machine | null>(null)
  const [archiving, setArchiving] = useState<Machine | null>(null)
  const [photos, setPhotos] = useState<Machine | null>(null)
  const [done, setDone] = useState<Machine | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const back = useAction((m: Machine) => backInService(m.id), { invalidate: [eqKeys.all], success: (r) => r.message })
  const arch = useAction((m: Machine) => archiveMachine(m.id, !!m.is_archived), { invalidate: [eqKeys.all], success: (r) => r.message, onSuccess: () => setArchiving(null) })
  const manage = can('stores.manage|workorders.manage')
  const columns: TableColumn<Machine>[] = [
    { id: 'code', header: 'ID', sort: (m) => m.code, cell: (m) => <span className="font-mono text-[13px] font-semibold">{m.code}</span> },
    { id: 'name', header: 'Machine', sort: (m) => m.name, cell: (m) => <div><button type="button" className="font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setOpen(m.id)}>{m.name}</button><div className="text-xs text-muted-foreground">{m.category}{m.brand && ` - ${m.brand} ${m.model}`}{m.reg_no && ` - ${m.reg_no}`} - {m.ownership_label ?? m.ownership}{m.ownership !== 'Owned' && m.hire_rate > 0 && ` at ${formatINR(m.hire_rate)}/${m.hire_basis.toLowerCase()}`}</div></div> },
    { id: 'status', header: 'Status', cell: (m) => <div className="flex flex-col items-start gap-0.5"><StatusBadge status={m.status} />{m.condition && m.condition !== 'Good' && <span className="text-xs text-warning">{m.condition} condition</span>}</div> },
    { id: 'where', header: 'Where', hideBelow: 'md', cell: (m) => m.where },
    { id: 'meter', header: 'Meter', hideBelow: 'lg', align: 'right', cell: (m) => <div>{m.meter_reading.toLocaleString('en-IN')} {m.meter_unit.toLowerCase()}{m.service.reasons.length > 0 && <div className={`text-xs ${m.service.due ? 'font-semibold text-danger' : 'text-warning'}`}>{m.service.reasons.join('; ')}</div>}</div> },
    {
      id: 'service', header: 'Service', hideBelow: 'md', sort: (m) => SERVICE_ORDER.indexOf(m.service.status),
      cell: (m) => {
        const s = m.service.schedule
        const next = [s.next_meter !== null ? `${s.next_meter.toLocaleString('en-IN')} ${s.unit}` : '', s.next_on ? formatDate(s.next_on) : ''].filter(Boolean).join(' or ')
        return <div className="flex flex-col items-start gap-0.5"><ServiceBadge status={m.service.status} />{next && <span className="text-xs text-muted-foreground">Next {next}</span>}</div>
      },
    },
    { id: 'cost', header: 'Cost to date', hideBelow: 'md', align: 'right', sort: (m) => m.cost_to_date, cell: (m) => formatINR(m.cost_to_date) },
    {
      id: 'act', header: '', align: 'right',
      cell: (m) => m.status === 'Disposed' ? null : (
        <div className="flex flex-wrap justify-end gap-1.5">
          {!m.is_archived && m.status !== 'Returned' && <>
            {!['Under repair', 'Breakdown'].includes(m.status) && <Button size="sm" variant="outline" onClick={() => setMoving(m)}>{m.current_job_id ? 'Move' : 'Deploy'}</Button>}
            {['Due soon', 'Service due', 'Overdue'].includes(m.service.status) && <Button size="sm" variant={m.service.due ? 'primary' : 'outline'} onClick={() => setDone(m)}>Service done</Button>}
            {['Under repair', 'Breakdown'].includes(m.status) ? <Button size="sm" loading={back.isPending && back.variables?.id === m.id} onClick={() => back.mutate(m)}>Back at work</Button> : <Button size="sm" variant="outline" onClick={() => setServicing(m)}>Service</Button>}
            {manage && <Button size="sm" variant="ghost" onClick={() => setEditing(m)}>Edit</Button>}
          </>}
          <Button size="sm" variant="ghost" aria-label={`Photo and documents of ${m.code}`} onClick={() => setPhotos(m)}><Image /></Button>
          {manage && <Button size="sm" variant="ghost" aria-label={m.is_archived ? `Restore ${m.code}` : `Archive ${m.code}`} title={m.is_archived ? 'Restore' : 'Archive'} onClick={() => setArchiving(m)}>{m.is_archived ? <RotateCcw /> : <Archive />}</Button>}
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="equipment" id={r.id} label={String(r.name)} noun="equipment" /> },
  ]
  const filters = useListFilters(q.data?.assets, {
    search: (m) => [m.code, m.name, m.category, m.brand, m.model, m.reg_no, m.current_job, m.hired_from, STATUS_LABEL[m.status] ?? m.status, m.ownership_label].join(' '),
    status: (m) => STATUS_LABEL[m.status] ?? m.status,
    date: (m) => m.purchase_date,
    facets: { ownership: { label: 'Ownership', get: (m) => m.ownership_label ?? m.ownership }, service: { label: 'Service', get: (m) => m.service.status } },
  })
  const { shown, pager } = usePaged(filters.filtered)
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-44"><Select aria-label="Machine status" value={status} placeholder="Every machine" onChange={(e) => setStatus(e.target.value)} options={['Deployed', 'Available', 'Under repair', 'Breakdown', 'Returned', 'Disposed'].map((x) => ({ value: x, label: STATUS_LABEL[x] ?? x }))} /></div>
        <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived</label>
        {manage && <Button className="ml-auto" onClick={() => setEditing('new')}><Plus /> Machine</Button>}
      </div>
      <FilterBar filters={filters} placeholder="Search by ID, name, brand, registration..." />
      <Card className="overflow-hidden"><DataTable label="Machines" className="rounded-none border-0 shadow-none" rows={shown} columns={columns} rowKey={(m) => m.id} loading={q.isPending} empty={archived ? 'No archived machines.' : 'No machines on the register yet. Add what the business owns, and what it hires in.'} />{!q.isPending && pager}</Card>
      {open && <MachineDetail id={open} onClose={() => setOpen(null)} />}
      <MachineModal machine={editing && editing !== 'new' ? editing : null} categories={q.data?.categories ?? []} open={!!editing} onClose={() => setEditing(null)} />
      <MoveModal machine={moving} onClose={() => setMoving(null)} />
      <ServiceModal machine={servicing} onClose={() => setServicing(null)} />
      <ServiceDoneModal machine={done} onClose={() => setDone(null)} />
      <ConfirmDialog open={!!archiving} onOpenChange={(o) => !o && setArchiving(null)} title={archiving ? `${archiving.is_archived ? 'Restore' : 'Archive'} ${archiving.code} ${archiving.name}?` : ''} description={archiving?.is_archived ? 'It comes back onto the working register.' : 'It leaves the working register. Its logs, costs and history are kept.'} confirmLabel="Yes" cancelLabel="Cancel" loading={arch.isPending} onConfirm={() => { if (archiving) arch.mutate(archiving) }} />
      {photos && <FilesModal type="equipment" id={photos.id} title={`${photos.code} ${photos.name} - photo and documents`} onClose={() => setPhotos(null)} />}
    </>
  )
}
