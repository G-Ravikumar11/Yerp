import { useState } from 'react'
import { Plus, Printer } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Select, Textarea } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useProjects, projectLabel } from '@/api/projects'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storeDelete, storePerm, storePost, storePut, useScanning, useStoreMeta } from '@/api/store'
import StoreLevels from './StoreLevels'
import { mastersInvalidate, useAssignments, useBins, useEmployeeOptions, useStores, type AssignRow, type BinRow, type StoreRow } from './api'

/** What a person does in a store (the server holds the same list). What they may do comes from their access level. */
const STORE_JOBS: Record<string, string> = { STOREKEEPER: 'Storekeeper', STORE_INCHARGE: 'Store in-charge', ASSISTANT: 'Store assistant', GATE: 'Gate / security', SITE_ENGINEER: 'Site engineer (asks for material)', VIEWER: 'Looks up stock' }

const money = (v: string) => Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Store > Masters > Stores: the places stock is kept, and who works in each. */
export default function StoresPage() {
  const { can } = useSession()
  const [status, setStatus] = useState('active')
  const [q, setQ] = useState('')
  const stores = useStores(status, q)
  const [editing, setEditing] = useState<StoreRow | 'new' | null>(null)
  const [open, setOpen] = useState<StoreRow | null>(null)
  const [closing, setClosing] = useState<StoreRow | null>(null)
  const canEdit = can(storePerm('masters', 'create'))
  const canClose = can(storePerm('masters', 'approve'))
  const toggle = useAction((s: StoreRow) => storePost<StoreRow>('masters', `/stores/${s.id}/${s.is_active ? 'deactivate' : 'activate'}`), {
    invalidate: [...mastersInvalidate],
    success: (s) => (s.is_active ? 'Store is in use again' : 'Store taken out of use'),
  })

  const columns: TableColumn<StoreRow>[] = [
    { id: 'code', header: 'Code', width: '6rem', sort: (s) => s.code, cell: (s) => <span className="font-mono text-[13px] font-medium">{s.code}</span> },
    { id: 'name', header: 'Store', sort: (s) => s.name, cell: (s) => <div><div className="font-medium">{s.name}</div>{s.address && <div className="text-xs text-muted-foreground">{s.address}</div>}</div> },
    { id: 'type', header: 'Type', width: '6rem', hideBelow: 'sm', cell: (s) => <Badge>{s.type}</Badge> },
    { id: 'project', header: 'Project', hideBelow: 'md', cell: (s) => s.project_name || '-' },
    { id: 'held', header: 'Items held', align: 'right', width: '6rem', hideBelow: 'md', sort: (s) => s.items_held, cell: (s) => s.items_held },
    { id: 'value', header: 'Stock value', align: 'right', width: '8rem', hideBelow: 'sm', sort: (s) => Number(s.stock_value), cell: (s) => money(s.stock_value) },
    { id: 'bins', header: 'Bins', align: 'right', width: '4rem', hideBelow: 'lg', cell: (s) => s.bins },
    { id: 'staff', header: 'Staff', align: 'right', width: '4rem', hideBelow: 'lg', cell: (s) => s.staff },
    {
      id: 'state',
      header: 'Status',
      width: '7rem',
      cell: (s) => (s.frozen ? <Badge tone="warning" dot>Frozen</Badge> : s.is_active ? <Badge tone="success" dot>In use</Badge> : <Badge dot>Out of use</Badge>),
    },
  ]

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Show" htmlFor="st-status" className="w-40">
          <Select id="st-status" value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: 'active', label: 'In use' }, { value: 'inactive', label: 'Out of use' }, { value: 'all', label: 'All stores' }]} />
        </Field>
        <Field label="Search" htmlFor="st-q" className="w-56">
          <Input id="st-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Code or name" />
        </Field>
        {canEdit && <Button className="ml-auto" onClick={() => setEditing('new')}><Plus /> New store</Button>}
      </div>
      {stores.isError ? (
        <p role="alert" className="text-sm text-danger">Could not load the stores.</p>
      ) : (
        <DataTable label="Stores" rows={stores.data ?? []} loading={stores.isPending} columns={columns} rowKey={(s) => s.id} onRowClick={setOpen} empty="No stores yet. Add the central store and one for each site." />
      )}
      {editing && <StoreFormModal store={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {open && (
        <StoreDetailModal
          store={open}
          canEdit={canEdit}
          canClose={canClose}
          onEdit={() => { setEditing(open); setOpen(null) }}
          onToggle={() => { if (open.is_active) setClosing(open); else toggle.mutate(open); setOpen(null) }}
          onClose={() => setOpen(null)}
        />
      )}
      <ConfirmDialog
        open={!!closing}
        onOpenChange={(o) => !o && setClosing(null)}
        title={`Take ${closing?.code ?? 'this store'} out of use?`}
        description="Nothing can be received into or issued from it afterwards. Its history stays. A store that still holds stock cannot be taken out of use."
        confirmLabel="Take out of use"
        tone="danger"
        onConfirm={() => { if (closing) toggle.mutate(closing); setClosing(null) }}
      />
    </div>
  )
}

function StoreFormModal({ store, onClose }: { store: StoreRow | null; onClose: () => void }) {
  const meta = useStoreMeta()
  const projects = useProjects()
  const [f, setF] = useState({ code: store?.code ?? '', name: store?.name ?? '', type: store?.type ?? 'CENTRAL', project_id: store?.project_id ?? 0, address: store?.address ?? '' })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const save = useAction(
    () => {
      const body = { code: f.code, name: f.name, type: f.type, project_id: f.project_id || null, address: f.address }
      return store ? storePut<StoreRow>('masters', `/stores/${store.id}`, body) : storePost<StoreRow>('masters', '/stores', body)
    },
    { invalidate: [...mastersInvalidate], success: store ? 'Store saved' : 'Store added', onSuccess: onClose },
  )
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={store ? `Edit ${store.code}` : 'New store'} description="The code is printed in every document number from this store (GRN/CS01/26-27/00042), so it cannot change once stock has moved.">
      <form onSubmit={(e) => { e.preventDefault(); if (f.code.trim() && f.name.trim()) save.mutate() }}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Code" htmlFor="sf-code" hint="2 to 12 capital letters or numbers."><Input id="sf-code" value={f.code} onChange={(e) => set('code', e.target.value.toUpperCase())} placeholder="CS01" autoFocus maxLength={12} /></Field>
          <Field label="Type" htmlFor="sf-type">
            <Select id="sf-type" value={f.type} onChange={(e) => set('type', e.target.value as typeof f.type)} options={(meta.data?.store_types ?? ['CENTRAL', 'SITE', 'YARD']).map((t) => ({ value: t, label: t }))} />
          </Field>
          <Field label="Name" htmlFor="sf-name" className="sm:col-span-2"><Input id="sf-name" value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="Central Store" maxLength={100} /></Field>
          <Field label="Project" htmlFor="sf-project" hint="A site store belongs to its project." className="sm:col-span-2">
            <Select id="sf-project" value={f.project_id || ''} placeholder="No project" onChange={(e) => set('project_id', Number(e.target.value) || 0)} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} />
          </Field>
          <Field label="Address" htmlFor="sf-address" className="sm:col-span-2"><Textarea id="sf-address" rows={2} value={f.address} onChange={(e) => set('address', e.target.value)} /></Field>
        </div>
        <div className="mt-5 flex justify-end gap-2 border-t border-border pt-4">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!f.code.trim() || !f.name.trim()}>{store ? 'Save' : 'Add store'}</Button>
        </div>
      </form>
    </Modal>
  )
}

function StoreDetailModal({ store, canEdit, canClose, onEdit, onToggle, onClose }: { store: StoreRow; canEdit: boolean; canClose: boolean; onEdit: () => void; onToggle: () => void; onClose: () => void }) {
  const bins = useBins(store.id)
  const scanning = useScanning()
  const staff = useAssignments(store.id)
  const [bin, setBin] = useState({ code: '', description: '' })
  const [who, setWho] = useState('')
  const [role, setRole] = useState('STOREKEEPER')
  const employees = useEmployeeOptions('')
  const refresh = [...mastersInvalidate]
  const addBin = useAction(() => storePost<BinRow>('masters', `/stores/${store.id}/bins`, bin), { invalidate: refresh, success: 'Bin added', onSuccess: () => setBin({ code: '', description: '' }) })
  const dropBin = useAction((id: number) => storeDelete<{ message: string }>('masters', `/bins/${id}`), { invalidate: refresh })
  const assign = useAction(() => storePost<AssignRow>('masters', `/stores/${store.id}/assignments`, { employee_id: Number(who), role }), { invalidate: refresh, success: 'Added to the store', onSuccess: () => setWho('') })
  const unassign = useAction((id: number) => storeDelete<{ message: string }>('masters', `/stores/${store.id}/assignments/${id}`), { invalidate: refresh })
  const working = (staff.data ?? []).filter((a) => a.is_active)
  const free = (employees.data ?? []).filter((e) => !working.some((a) => a.employee_id === e.id))
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={`${store.code} - ${store.name}`} description={`${store.type}${store.project_name ? ' - ' + store.project_name : ''}. ${store.items_held} items held, worth ${money(store.stock_value)}.`}>
      <div className="grid gap-6">
        {store.frozen && <p role="status" className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">Frozen for a stock count{store.frozen_reason ? `: ${store.frozen_reason}` : ''}. Nothing can move in or out until it is unfrozen.</p>}
        <section aria-labelledby="sd-bins">
          <div className="mb-2 flex flex-wrap items-center gap-2 border-b pb-1">
            <h3 id="sd-bins" className="mr-auto text-sm font-semibold">Bins</h3>
            {/* Sticky QR labels: a tag for each rack and yard bay, and a rack label for each item held - loose material carries none. */}
            {scanning && <Button size="sm" variant="ghost" asChild><a href={`/api/store/masters/labels.pdf?store_id=${store.id}&kind=bins`} target="_blank" rel="noreferrer"><Printer /> Bin labels</a></Button>}
            {scanning && <Button size="sm" variant="ghost" asChild><a href={`/api/store/masters/labels.pdf?store_id=${store.id}&kind=items`} target="_blank" rel="noreferrer"><Printer /> Rack labels for items</a></Button>}
          </div>
          {bins.isPending ? <p className="text-sm text-muted-foreground">Loading...</p> : (bins.data ?? []).length === 0 ? <p className="text-sm text-muted-foreground">No bins yet.</p> : (
            <ul className="divide-y rounded-lg border">
              {(bins.data ?? []).map((b) => (
                <li key={b.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                  <span><span className="font-mono font-medium">{b.code}</span>{b.description && <span className="ml-2 text-muted-foreground">{b.description}</span>}</span>
                  {canEdit && <Button size="sm" variant="ghost" aria-label={`Remove bin ${b.code}`} onClick={() => dropBin.mutate(b.id)}>Remove</Button>}
                </li>
              ))}
            </ul>
          )}
          {canEdit && (
            <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (bin.code.trim()) addBin.mutate() }}>
              <Field label="Bin code" htmlFor="sd-bin-code" className="w-32"><Input id="sd-bin-code" value={bin.code} onChange={(e) => setBin({ ...bin, code: e.target.value })} placeholder="A-01" maxLength={20} /></Field>
              <Field label="Description" htmlFor="sd-bin-desc" className="min-w-40 flex-1"><Input id="sd-bin-desc" value={bin.description} onChange={(e) => setBin({ ...bin, description: e.target.value })} placeholder="Cement shed" /></Field>
              <Button type="submit" variant="outline" loading={addBin.isPending} disabled={!bin.code.trim()}>Add bin</Button>
            </form>
          )}
        </section>
        <section aria-labelledby="sd-staff">
          <h3 id="sd-staff" className="mb-2 border-b pb-1 text-sm font-semibold">Who works here</h3>
          <p className="mb-2 text-xs text-muted-foreground">Staff can only see and work in the stores they are assigned to, whatever else they are allowed to do. Adding or removing someone needs the right to approve store masters.</p>
          {staff.isPending ? <p className="text-sm text-muted-foreground">Loading...</p> : working.length === 0 ? <p className="text-sm text-muted-foreground">Nobody is assigned yet.</p> : (
            <ul className="divide-y rounded-lg border">
              {working.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                  <span><span className="font-medium">{a.name}</span> <span className="text-muted-foreground">{a.email}</span> <Badge>{STORE_JOBS[a.role] ?? a.role}</Badge></span>
                  {canClose && <Button size="sm" variant="ghost" aria-label={`Remove ${a.name}`} onClick={() => unassign.mutate(a.employee_id)}>Remove</Button>}
                </li>
              ))}
            </ul>
          )}
          {canClose && (
            <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (who) assign.mutate() }}>
              <Field label="Employee" htmlFor="sd-emp" className="min-w-48 flex-1"><Select id="sd-emp" value={who} placeholder="Choose a person" onChange={(e) => setWho(e.target.value)} options={free.map((e) => ({ value: e.id, label: `${e.name}${e.job_title ? ' - ' + e.job_title : ''}` }))} /></Field>
              <Field label="Job in this store" htmlFor="sd-role" className="w-56"><Select id="sd-role" value={role} onChange={(e) => setRole(e.target.value)} options={Object.entries(STORE_JOBS).map(([value, label]) => ({ value, label }))} /></Field>
              <Button type="submit" variant="outline" loading={assign.isPending} disabled={!who}>Assign</Button>
            </form>
          )}
        </section>
        <StoreLevels storeId={store.id} canEdit={canEdit} />
        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
          {canClose && <Button variant="outline" onClick={onToggle}>{store.is_active ? 'Take out of use' : 'Bring back into use'}</Button>}
          {canEdit && <Button onClick={onEdit}>Edit store</Button>}
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </div>
    </Modal>
  )
}
