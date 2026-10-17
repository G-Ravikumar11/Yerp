import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Lock, LockOpen, Plus, Trash2 } from 'lucide-react'
import { Badge, Button, Card, ConfirmDialog, Input, Modal, Select, SkeletonRows, Tabs } from '@/components/ui'
import { useSession } from '@/lib/session'
import { toast } from '@/stores/toast'
import { storeDelete, storeGet, storeKeys, storePerm, storePost, storePut, useStoreMeta, type StoreType } from '@/api/store'
import { StoreShell } from '../StoreShell'

/** Store > Masters. Stores, bins, who works where, the freeze switch, and the per-item stock settings. */
interface StoreRow { id: number; code: string; name: string; type: StoreType; project_id: number | null; address: string; is_active: boolean; frozen: boolean; stock_lines: number }
interface BinRow { id: number; code: string; description: string; is_active: boolean }
interface AssignRow { id: number; employee_id: number; name: string; role: string; is_active: boolean }
interface EmployeeRow { id: number; name: string; job_title: string }
interface ItemRow {
  item_id: number; code: string; name: string; item_unit: string; configured: boolean; category: string; base_uom: string
  reorder_level: string; min_qty: string; max_qty: string; qc_required: boolean; over_receipt_tolerance_pct: string; is_batch_tracked: boolean
  conversions: { id: number; from_uom: string; to_base_factor: string }[]
}

const key = (...p: (string | number)[]) => ['store', 'masters', ...p]
const errText = (e: unknown) => (e as { detail?: string; message?: string })?.detail ?? (e as Error)?.message ?? 'Something went wrong'

export default function MastersIndex() {
  const { can } = useSession()
  const [tab, setTab] = useState<'stores' | 'items'>('stores')
  return (
    <StoreShell slice="masters">
      <Tabs label="Masters" value={tab} onChange={setTab} items={[{ value: 'stores', label: 'Stores' }, { value: 'items', label: 'Item settings' }]} />
      <div className="mt-6">{tab === 'stores' ? <StoresTab canEdit={can(storePerm('masters', 'create'))} canManage={can(storePerm('masters', 'approve'))} canOff={can(storePerm('masters', 'cancel'))} /> : <ItemsTab canEdit={can(storePerm('masters', 'create'))} canOff={can(storePerm('masters', 'cancel'))} />}</div>
    </StoreShell>
  )
}

/* ------------------------------------------------------------------------------------------------ stores */
function StoresTab({ canEdit, canManage, canOff }: { canEdit: boolean; canManage: boolean; canOff: boolean }) {
  const qc = useQueryClient()
  const meta = useStoreMeta()
  const [showOff, setShowOff] = useState(false)
  const [edit, setEdit] = useState<Partial<StoreRow> | null>(null)
  const [open, setOpen] = useState<StoreRow | null>(null)
  const list = useQuery({ queryKey: key('stores', String(showOff)), queryFn: () => storeGet<{ stores: StoreRow[] }>('masters', `/stores?include_inactive=${showOff}`) })
  const save = useMutation({
    mutationFn: (s: Partial<StoreRow>) => (s.id ? storePut('masters', `/stores/${s.id}`, s) : storePost('masters', '/stores', s)),
    onSuccess: () => { toast.success('Store saved'); setEdit(null); qc.invalidateQueries({ queryKey: storeKeys.all }) },
    onError: (e) => toast.error(errText(e)),
  })
  const stores = list.data?.stores ?? []
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm text-muted-foreground"><input type="checkbox" checked={showOff} onChange={(e) => setShowOff(e.target.checked)} /> Show switched-off stores</label>
        {canEdit && <Button onClick={() => setEdit({ type: 'SITE' })}><Plus /> Add store</Button>}
      </div>
      {list.isLoading ? <SkeletonRows rows={4} cols={4} /> : stores.length === 0 ? <p className="text-sm text-muted-foreground">No stores yet.</p> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Code</th><th className="p-3">Name</th><th className="p-3">Type</th><th className="p-3 text-right">Items held</th><th className="p-3">Status</th></tr></thead>
            <tbody>
              {stores.map((s) => (
                <tr key={s.id} className="cursor-pointer border-b border-border last:border-0 hover:bg-accent/40" onClick={() => setOpen(s)}>
                  <td className="p-3 font-mono">{s.code}</td><td className="p-3">{s.name}</td><td className="p-3">{s.type}</td><td className="p-3 text-right">{s.stock_lines}</td>
                  <td className="p-3">{!s.is_active ? <Badge tone="neutral">Off</Badge> : s.frozen ? <Badge tone="warning">Frozen</Badge> : <Badge tone="success">Active</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {edit && (
        <Modal open onOpenChange={() => setEdit(null)} title={edit.id ? 'Edit store' : 'Add store'} footer={<><Button variant="outline" onClick={() => setEdit(null)}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate(edit)}>Save</Button></>}>
          <div className="grid gap-3">
            <label className="text-sm">Code<Input value={edit.code ?? ''} disabled={!!edit.id} onChange={(e) => setEdit({ ...edit, code: e.target.value })} placeholder="CS01" /></label>
            <label className="text-sm">Name<Input value={edit.name ?? ''} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label>
            <label className="text-sm">Type<Select value={edit.type ?? 'SITE'} options={(meta.data?.store_types ?? ['CENTRAL', 'SITE', 'YARD']).map((t) => ({ value: t, label: t }))} onChange={(e) => setEdit({ ...edit, type: e.target.value as StoreType })} /></label>
            <label className="text-sm">Address<Input value={edit.address ?? ''} onChange={(e) => setEdit({ ...edit, address: e.target.value })} /></label>
          </div>
        </Modal>
      )}
      {open && <StoreDetail store={open} canEdit={canEdit} canManage={canManage} canOff={canOff} onClose={() => setOpen(null)} onEdit={() => { setEdit(open); setOpen(null) }} />}
    </div>
  )
}

function StoreDetail({ store, canEdit, canManage, canOff, onClose, onEdit }: { store: StoreRow; canEdit: boolean; canManage: boolean; canOff: boolean; onClose: () => void; onEdit: () => void }) {
  const qc = useQueryClient()
  const done = () => qc.invalidateQueries({ queryKey: storeKeys.all })
  const bins = useQuery({ queryKey: key('bins', store.id), queryFn: () => storeGet<{ bins: BinRow[] }>('masters', `/stores/${store.id}/bins`) })
  const staff = useQuery({ queryKey: key('assign', store.id), queryFn: () => storeGet<{ assignments: AssignRow[] }>('masters', `/stores/${store.id}/assignments`) })
  const emps = useQuery({ queryKey: key('employees'), enabled: canManage, queryFn: () => storeGet<{ employees: EmployeeRow[] }>('masters', '/employees') })
  const [bin, setBin] = useState('')
  const [emp, setEmp] = useState('')
  const [freezeOpen, setFreezeOpen] = useState(false)
  const [offOpen, setOffOpen] = useState(false)
  const run = (fn: () => Promise<unknown>, msg: string) => fn().then(() => { toast.success(msg); done() }).catch((e) => toast.error(errText(e)))
  return (
    <Modal open onOpenChange={onClose} size="lg" title={`${store.code} · ${store.name}`} description={`${store.type} store`}>
      <div className="space-y-6">
        <div className="flex flex-wrap gap-2">
          {canEdit && <Button variant="outline" size="sm" onClick={onEdit}>Edit</Button>}
          {canManage && store.is_active && (store.frozen
            ? <Button variant="outline" size="sm" onClick={() => run(() => storePost('masters', `/stores/${store.id}/unfreeze`), 'Store unfrozen').then(onClose)}><LockOpen /> Unfreeze</Button>
            : <Button variant="outline" size="sm" onClick={() => setFreezeOpen(true)}><Lock /> Freeze for stock count</Button>)}
          {canOff && (store.is_active
            ? <Button variant="danger" size="sm" onClick={() => setOffOpen(true)}>Switch off</Button>
            : <Button variant="outline" size="sm" onClick={() => run(() => storePut('masters', `/stores/${store.id}`, { is_active: true }), 'Store switched on').then(onClose)}>Switch on</Button>)}
        </div>
        <section>
          <h3 className="mb-2 text-sm font-semibold">Bins</h3>
          <ul className="mb-2 space-y-1 text-sm">{(bins.data?.bins ?? []).map((b) => <li key={b.id} className="flex justify-between"><span><span className="font-mono">{b.code}</span> {b.description}</span>{!b.is_active && <Badge>Off</Badge>}</li>)}{bins.data?.bins.length === 0 && <li className="text-muted-foreground">No bins.</li>}</ul>
          {canEdit && <div className="flex gap-2"><Input value={bin} onChange={(e) => setBin(e.target.value)} placeholder="New bin code" /><Button variant="outline" disabled={!bin.trim()} onClick={() => run(() => storePost('masters', `/stores/${store.id}/bins`, { code: bin }), 'Bin added').then(() => setBin(''))}>Add</Button></div>}
        </section>
        <section>
          <h3 className="mb-2 text-sm font-semibold">Who works here</h3>
          <ul className="mb-2 space-y-1 text-sm">
            {(staff.data?.assignments ?? []).filter((a) => a.is_active).map((a) => (
              <li key={a.id} className="flex items-center justify-between"><span>{a.name} <span className="text-muted-foreground">· {a.role}</span></span>{canManage && <Button variant="ghost" size="icon-sm" aria-label={`Remove ${a.name}`} onClick={() => run(() => storeDelete('masters', `/assignments/${a.id}`), 'Removed')}><Trash2 /></Button>}</li>
            ))}
            {!(staff.data?.assignments ?? []).some((a) => a.is_active) && <li className="text-muted-foreground">Nobody assigned: only the account holder and store administrators can use this store.</li>}
          </ul>
          {canManage && <div className="flex gap-2"><Select value={emp} placeholder="Choose staff" options={(emps.data?.employees ?? []).map((e) => ({ value: e.id, label: e.name }))} onChange={(e) => setEmp(e.target.value)} /><Button variant="outline" disabled={!emp} onClick={() => run(() => storePost('masters', `/stores/${store.id}/assignments`, { employee_id: Number(emp) }), 'Assigned').then(() => setEmp(''))}>Assign</Button></div>}
        </section>
      </div>
      <ConfirmDialog open={freezeOpen} onOpenChange={setFreezeOpen} title="Freeze this store?" description="Nothing can be received or issued here until it is unfrozen." confirmLabel="Freeze" reason={{ label: 'Reason', placeholder: 'Annual stock count', required: true }}
        onConfirm={(reason) => run(() => storePost('masters', `/stores/${store.id}/freeze`, { reason }), 'Store frozen').then(() => { setFreezeOpen(false); onClose() })} />
      <ConfirmDialog open={offOpen} onOpenChange={setOffOpen} tone="danger" title="Switch this store off?" description="It will no longer appear in pickers. A store that still holds stock cannot be switched off." confirmLabel="Switch off"
        onConfirm={() => run(() => storePut('masters', `/stores/${store.id}`, { is_active: false }), 'Store switched off').then(() => { setOffOpen(false); onClose() })} />
    </Modal>
  )
}

/* ------------------------------------------------------------------------------------------------ items */
function ItemsTab({ canEdit, canOff }: { canEdit: boolean; canOff: boolean }) {
  const [q, setQ] = useState('')
  const [only, setOnly] = useState<'all' | 'gaps'>('all')
  const [row, setRow] = useState<ItemRow | null>(null)
  const list = useQuery({
    queryKey: key('items', q, only),
    queryFn: () => storeGet<{ items: ItemRow[]; total: number }>('masters', `/items?q=${encodeURIComponent(q)}${only === 'gaps' ? '&configured=false' : ''}`),
  })
  const items = list.data?.items ?? []
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <Input className="max-w-xs" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search item code or name" />
        <Select className="w-48" value={only} options={[{ value: 'all', label: 'All stock items' }, { value: 'gaps', label: 'Settings missing' }]} onChange={(e) => setOnly(e.target.value as 'all' | 'gaps')} />
      </div>
      {list.isLoading ? <SkeletonRows rows={6} cols={5} /> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Item</th><th className="p-3">Category</th><th className="p-3">Base unit</th><th className="p-3 text-right">Reorder at</th><th className="p-3">Settings</th></tr></thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.item_id} className="cursor-pointer border-b border-border last:border-0 hover:bg-accent/40" onClick={() => setRow(i)}>
                  <td className="p-3"><span className="font-mono text-xs text-muted-foreground">{i.code}</span> {i.name}</td><td className="p-3">{i.category}</td><td className="p-3">{i.base_uom}</td><td className="p-3 text-right">{i.reorder_level}</td>
                  <td className="p-3">{i.configured ? <Badge tone="success">Set</Badge> : <Badge tone="warning">Missing</Badge>}</td>
                </tr>
              ))}
              {items.length === 0 && <tr><td colSpan={5} className="p-6 text-center text-muted-foreground">No items.</td></tr>}
            </tbody>
          </table>
        </Card>
      )}
      {row && <ItemEditor item={row} canEdit={canEdit} canOff={canOff} onClose={() => setRow(null)} />}
    </div>
  )
}

function ItemEditor({ item, canEdit, canOff, onClose }: { item: ItemRow; canEdit: boolean; canOff: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const meta = useStoreMeta()
  const [f, setF] = useState(item)
  const [unit, setUnit] = useState('')
  const [factor, setFactor] = useState('')
  const refresh = () => qc.invalidateQueries({ queryKey: storeKeys.all })
  const save = useMutation({
    mutationFn: () => storePut<ItemRow>('masters', `/items/${item.item_id}/settings`, f),
    onSuccess: (r) => { toast.success('Settings saved'); setF(r); refresh() },
    onError: (e) => toast.error(errText(e)),
  })
  const addConv = useMutation({
    mutationFn: () => storePost('masters', `/items/${item.item_id}/uoms`, { from_uom: unit, to_base_factor: factor }),
    onSuccess: () => { toast.success('Conversion saved'); setUnit(''); setFactor(''); onClose(); refresh() },
    onError: (e) => toast.error(errText(e)),
  })
  const num = (k: 'reorder_level' | 'min_qty' | 'max_qty' | 'over_receipt_tolerance_pct', label: string) => (
    <label className="text-sm">{label}<Input inputMode="decimal" disabled={!canEdit} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
  )
  return (
    <Modal open onOpenChange={onClose} size="lg" title={item.name} description={item.code} footer={canEdit ? <><Button variant="outline" onClick={onClose}>Close</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Save settings</Button></> : undefined}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">Category<Select disabled={!canEdit} value={f.category} options={(meta.data?.item_categories ?? ['CONSUMABLE']).map((c) => ({ value: c, label: c }))} onChange={(e) => setF({ ...f, category: e.target.value })} /></label>
        <label className="text-sm">Base unit<Input disabled={!canEdit} value={f.base_uom} onChange={(e) => setF({ ...f, base_uom: e.target.value })} /></label>
        {num('reorder_level', 'Reorder level')}{num('min_qty', 'Minimum')}{num('max_qty', 'Maximum')}{num('over_receipt_tolerance_pct', 'Over-receipt tolerance %')}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!canEdit} checked={f.qc_required} onChange={(e) => setF({ ...f, qc_required: e.target.checked })} /> Quality check on receipt</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!canEdit} checked={f.is_batch_tracked} onChange={(e) => setF({ ...f, is_batch_tracked: e.target.checked })} /> Track by batch</label>
      </div>
      <h3 className="mb-2 mt-6 text-sm font-semibold">Unit conversions <span className="font-normal text-muted-foreground">(1 unit = this many {f.base_uom})</span></h3>
      <ul className="mb-2 space-y-1 text-sm">
        {f.conversions.map((c) => (
          <li key={c.id} className="flex items-center justify-between"><span>1 {c.from_uom} = {c.to_base_factor} {f.base_uom}</span>
            {canOff && <Button variant="ghost" size="icon-sm" aria-label={`Remove ${c.from_uom}`} onClick={() => storeDelete('masters', `/uoms/${c.id}`).then(() => { toast.success('Removed'); onClose(); refresh() }).catch((e) => toast.error(errText(e)))}><Trash2 /></Button>}
          </li>
        ))}
        {f.conversions.length === 0 && <li className="text-muted-foreground">None.</li>}
      </ul>
      {canEdit && f.configured && <div className="flex gap-2"><Input value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="Unit (bag)" /><Input inputMode="decimal" value={factor} onChange={(e) => setFactor(e.target.value)} placeholder={`Factor in ${f.base_uom}`} /><Button variant="outline" disabled={!unit.trim() || !factor} loading={addConv.isPending} onClick={() => addConv.mutate()}>Add</Button></div>}
      {canEdit && !f.configured && <p className="text-xs text-muted-foreground">Save the settings first, then add unit conversions.</p>}
    </Modal>
  )
}
