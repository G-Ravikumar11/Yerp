import { useState } from 'react'
import { Plus, Snowflake } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Field, Input, Modal, Select, Tabs, Textarea } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { storeKeys, storePerm, type StoreType } from '@/api/store'
import {
  addBin, assign, mastersKeys, ROLE_LABEL, saveStore, STORE_TYPE_LABEL, updateAssignment, updateBin, useAssignments, useBins,
  useEmployees, useStores, type StoreRow,
} from './api'

const refresh = { invalidate: [mastersKeys.all, storeKeys.stores()] }

/** Masters > Stores: every store of the company, and for each its bins and the people who work in it. */
export function StoresTab() {
  const { can } = useSession()
  const manage = can(storePerm('masters', 'create'))
  const [inactive, setInactive] = useState(false)
  const stores = useStores(inactive)
  const [editing, setEditing] = useState<StoreRow | 'new' | null>(null)
  const [open, setOpen] = useState<StoreRow | null>(null)
  const cols: TableColumn<StoreRow>[] = [
    { id: 'code', header: 'Code', width: '6rem', sort: (s) => s.code, cell: (s) => <span className="font-mono font-semibold">{s.code}</span> },
    {
      id: 'name',
      header: 'Store',
      sort: (s) => s.name,
      cell: (s) => (
        <div>
          {s.name}
          {s.project && <div className="text-xs text-muted-foreground">{s.project}</div>}
        </div>
      ),
    },
    { id: 'type', header: 'Type', width: '7rem', cell: (s) => STORE_TYPE_LABEL[s.type] ?? s.type },
    { id: 'bins', header: 'Bins', align: 'right', width: '5rem', hideBelow: 'md', cell: (s) => s.bins },
    { id: 'users', header: 'People', align: 'right', width: '5rem', hideBelow: 'md', cell: (s) => s.users },
    {
      id: 'state',
      header: '',
      width: '9rem',
      cell: (s) => (
        <div className="flex flex-wrap gap-1">
          {!s.is_active && <Badge>Closed</Badge>}
          {s.frozen && <Badge tone="info"><Snowflake className="size-3" /> Frozen</Badge>}
          {!s.accessible && <Badge tone="warning">Not yours</Badge>}
        </div>
      ),
    },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (s) =>
        manage && (
          <Button size="sm" variant="outline" onClick={(e) => { e.stopPropagation(); setEditing(s) }}>
            Edit
          </Button>
        ),
    },
  ]
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} /> Show closed stores
        </label>
        {manage && <Button onClick={() => setEditing('new')}><Plus /> New store</Button>}
      </div>
      <DataTable
        label="Stores"
        rows={stores.data ?? []}
        columns={cols}
        rowKey={(s) => s.id}
        loading={stores.isPending}
        onRowClick={(s) => s.accessible && setOpen(s)}
        empty="No stores yet. Add the central store first, then a site store for each project."
      />
      {editing && <StoreForm store={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {open && <StoreDetail store={open} manage={manage} onClose={() => setOpen(null)} />}
    </div>
  )
}

function StoreForm({ store, onClose }: { store: StoreRow | null; onClose: () => void }) {
  const [f, setF] = useState({
    code: store?.code ?? '', name: store?.name ?? '', type: (store?.type ?? 'CENTRAL') as StoreType, project_id: store?.project_id ?? 0,
    address: store?.address ?? '', is_active: store?.is_active ?? true,
  })
  // 0 = no project (the server reads a missing project_id as "leave it as it is")
  const save = useAction(() => saveStore(store?.id ?? null, f), {
    ...refresh, success: store ? 'Store saved.' : 'Store added.', onSuccess: onClose,
  })
  const site = f.type === 'SITE'
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={store ? `Edit ${store.code}` : 'New store'}
      description="The code appears in every document number from this store (GRN/CS01/26-27/00001)."
      footer={<><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button></>}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Code" htmlFor="st-code" hint="2-10 capital letters or digits">
          <Input id="st-code" value={f.code} maxLength={10} onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '') })} />
        </Field>
        <Field label="Type" htmlFor="st-type">
          <Select id="st-type" value={f.type} options={(['CENTRAL', 'SITE', 'YARD'] as const).map((t) => ({ value: t, label: STORE_TYPE_LABEL[t] }))} onChange={(e) => setF({ ...f, type: e.target.value as StoreType })} />
        </Field>
        <Field label="Name" htmlFor="st-name" className="sm:col-span-2">
          <Input id="st-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label={site ? 'Project' : 'Project (optional)'} htmlFor="st-project" hint={site ? 'A site store belongs to its project.' : undefined} className="sm:col-span-2">
          <ProjectPicker id="st-project" value={f.project_id} onChange={(id) => setF((x) => ({ ...x, project_id: id }))} allowAll={!site} className="w-full" />
        </Field>
        <Field label="Address" htmlFor="st-addr" className="sm:col-span-2">
          <Textarea id="st-addr" rows={2} value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} />
        </Field>
        {store && (
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Open for use
            <span className="text-xs text-muted-foreground">(a store that still holds stock cannot be closed)</span>
          </label>
        )}
      </div>
    </Modal>
  )
}

function StoreDetail({ store, manage, onClose }: { store: StoreRow; manage: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<'bins' | 'people'>('people')
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={`${store.code} - ${store.name}`} description={store.project || STORE_TYPE_LABEL[store.type]}>
      <div className="mb-4">
        <Tabs label="Store details" value={tab} onChange={setTab} items={[{ value: 'people', label: 'People', count: store.users }, { value: 'bins', label: 'Bins', count: store.bins }]} />
      </div>
      {tab === 'bins' ? <Bins storeId={store.id} manage={manage} /> : <People storeId={store.id} manage={manage} />}
    </Modal>
  )
}

function Bins({ storeId, manage }: { storeId: number; manage: boolean }) {
  const bins = useBins(storeId)
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const add = useAction(() => addBin(storeId, { code, description }), { ...refresh, success: 'Bin added.', onSuccess: () => { setCode(''); setDescription('') } })
  const toggle = useAction((b: { id: number; on: boolean }) => updateBin(b.id, { is_active: b.on }), { ...refresh, success: false })
  return (
    <div className="space-y-3">
      {manage && (
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (code.trim()) add.mutate() }}>
          <Field label="Bin code" htmlFor="bin-code" className="w-32"><Input id="bin-code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="A-01" /></Field>
          <Field label="Where" htmlFor="bin-desc" className="min-w-0 flex-1"><Input id="bin-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Cement shed, rack 1" /></Field>
          <Button type="submit" loading={add.isPending} disabled={!code.trim()}>Add</Button>
        </form>
      )}
      <DataTable
        label="Bins"
        rows={bins.data ?? []}
        rowKey={(b) => b.id}
        loading={bins.isPending}
        empty="No bins. Stock can be held without them."
        columns={[
          { id: 'code', header: 'Code', width: '7rem', cell: (b) => <span className="font-mono">{b.code}</span> },
          { id: 'desc', header: 'Where', cell: (b) => b.description || '-' },
          {
            id: 'on',
            header: '',
            align: 'right',
            cell: (b) =>
              manage ? (
                <Button size="sm" variant="outline" onClick={() => toggle.mutate({ id: b.id, on: !b.is_active })}>{b.is_active ? 'Retire' : 'Bring back'}</Button>
              ) : (
                !b.is_active && <Badge>Retired</Badge>
              ),
          },
        ]}
      />
    </div>
  )
}

function People({ storeId, manage }: { storeId: number; manage: boolean }) {
  const users = useAssignments(storeId)
  const [q, setQ] = useState('')
  const [who, setWho] = useState(0)
  const [role, setRole] = useState('STOREKEEPER')
  const found = useEmployees(q, manage)
  const roles = users.data?.roles ?? Object.keys(ROLE_LABEL)
  const add = useAction(() => assign(storeId, { employee_id: who, role }), { ...refresh, success: (a) => `${a.name} can now work in this store.`, onSuccess: () => setWho(0) })
  const change = useAction((v: { id: number; role?: string; is_active?: boolean }) => updateAssignment(v.id, v), { ...refresh, success: false })
  return (
    <div className="space-y-3">
      {manage && (
        <div className="grid gap-2 sm:grid-cols-[1fr_1fr_10rem_auto] sm:items-end">
          <Field label="Find staff" htmlFor="ppl-q"><Input id="ppl-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or email" /></Field>
          <Field label="Person" htmlFor="ppl-who">
            <Select id="ppl-who" placeholder="Choose" value={who || ''} options={(found.data ?? []).map((e) => ({ value: e.id, label: e.job_title ? `${e.name} (${e.job_title})` : e.name }))} onChange={(e) => setWho(Number(e.target.value) || 0)} />
          </Field>
          <Field label="Role" htmlFor="ppl-role">
            <Select id="ppl-role" value={role} options={roles.map((r) => ({ value: r, label: ROLE_LABEL[r] ?? r }))} onChange={(e) => setRole(e.target.value)} />
          </Field>
          <Button loading={add.isPending} disabled={!who} onClick={() => add.mutate()}>Add</Button>
        </div>
      )}
      <p className="text-xs text-muted-foreground">Only the people listed here (and store administrators) can work in this store. What each may do comes from their store rights; the role is a label.</p>
      <DataTable
        label="People"
        rows={users.data?.users ?? []}
        rowKey={(a) => a.id}
        loading={users.isPending}
        empty="Nobody is assigned yet."
        columns={[
          { id: 'name', header: 'Person', cell: (a) => <div>{a.name}<div className="text-xs text-muted-foreground">{a.email}</div></div> },
          {
            id: 'role',
            header: 'Role',
            width: '11rem',
            cell: (a) =>
              manage ? (
                <Select aria-label={`Role of ${a.name}`} value={a.role} options={roles.map((r) => ({ value: r, label: ROLE_LABEL[r] ?? r }))} onChange={(e) => change.mutate({ id: a.id, role: e.target.value })} />
              ) : (
                ROLE_LABEL[a.role] ?? a.role
              ),
          },
          {
            id: 'on',
            header: '',
            align: 'right',
            cell: (a) =>
              manage ? (
                <Button size="sm" variant="outline" onClick={() => change.mutate({ id: a.id, is_active: !a.is_active })}>{a.is_active ? 'Take off' : 'Put back'}</Button>
              ) : (
                !a.is_active && <Badge>Off</Badge>
              ),
          },
        ]}
      />
    </div>
  )
}
