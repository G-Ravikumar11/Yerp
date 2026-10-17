import { useState } from 'react'
import { Badge, Button, Field, Input, Modal, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storeDelete, storePerm, storePut, useStoreMeta } from '@/api/store'
import { mastersInvalidate, useMasterItems, type ItemRow, type ItemSettings } from './api'

/** Store > Masters > Item settings: how the store treats each stock item - its unit, its limits and the units it can be counted in. */
export default function ItemSettingsPage() {
  const { can } = useSession()
  const [q, setQ] = useState('')
  const [category, setCategory] = useState('')
  const [configured, setConfigured] = useState('all')
  const items = useMasterItems(q, category, configured)
  const meta = useStoreMeta()
  const [editing, setEditing] = useState<ItemRow | null>(null)
  const canEdit = can(storePerm('masters', 'create'))

  const columns: TableColumn<ItemRow>[] = [
    { id: 'code', header: 'Code', width: '9rem', sort: (i) => i.code, cell: (i) => <span className="font-mono text-[13px]">{i.code}</span> },
    { id: 'name', header: 'Item', sort: (i) => i.name, cell: (i) => <span className="font-medium">{i.name}</span> },
    { id: 'cat', header: 'Category', width: '8rem', hideBelow: 'sm', cell: (i) => (i.configured ? <Badge>{i.settings.category}</Badge> : <span className="text-muted-foreground">-</span>) },
    { id: 'uom', header: 'Base unit', width: '6rem', cell: (i) => i.settings.base_uom || '-' },
    { id: 'conv', header: 'Also counted in', hideBelow: 'md', cell: (i) => (i.conversions.length ? i.conversions.map((c) => `${c.uom} (${Number(c.to_base_factor)})`).join(', ') : '-') },
    { id: 'reorder', header: 'Reorder at', align: 'right', width: '7rem', hideBelow: 'lg', cell: (i) => Number(i.settings.reorder_level) || '-' },
    { id: 'held', header: 'On hand', align: 'right', width: '7rem', sort: (i) => Number(i.on_hand), cell: (i) => Number(i.on_hand).toLocaleString('en-IN') },
    { id: 'state', header: '', width: '8rem', cell: (i) => (i.configured ? <Badge tone="success" dot>Set up</Badge> : <Badge tone="warning" dot>Defaults</Badge>) },
  ]

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Search" htmlFor="is-q" className="w-56"><Input id="is-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Item code or name" /></Field>
        <Field label="Category" htmlFor="is-cat" className="w-44">
          <Select id="is-cat" value={category} placeholder="Any category" onChange={(e) => setCategory(e.target.value)} options={(meta.data?.item_categories ?? []).map((c) => ({ value: c, label: c }))} />
        </Field>
        <Field label="Settings" htmlFor="is-cfg" className="w-44">
          <Select id="is-cfg" value={configured} onChange={(e) => setConfigured(e.target.value)} options={[{ value: 'all', label: 'All items' }, { value: 'yes', label: 'Set up' }, { value: 'no', label: 'Still on defaults' }]} />
        </Field>
      </div>
      <p className="mb-3 text-xs text-muted-foreground">Items come from the item master. An item on defaults is counted in its own unit as a consumable until you set it up here.</p>
      {items.isError ? <p role="alert" className="text-sm text-danger">Could not load the items.</p> : (
        <DataTable label="Item settings" rows={items.data?.items ?? []} loading={items.isPending} columns={columns} rowKey={(i) => i.id} onRowClick={setEditing} empty="No stock items match." />
      )}
      {editing && <ItemModal key={editing.id} item={editing} canEdit={canEdit} onClose={() => setEditing(null)} />}
    </div>
  )
}

function ItemModal({ item, canEdit, onClose }: { item: ItemRow; canEdit: boolean; onClose: () => void }) {
  const meta = useStoreMeta()
  const [s, setS] = useState<ItemSettings>(item.settings)
  const [conv, setConv] = useState(item.conversions)
  const [add, setAdd] = useState({ uom: '', factor: '' })
  const set = <K extends keyof ItemSettings>(k: K, v: ItemSettings[K]) => setS((x) => ({ ...x, [k]: v }))
  const save = useAction(() => storePut<ItemRow>('masters', `/items/${item.id}/settings`, s), {
    invalidate: [...mastersInvalidate],
    success: 'Settings saved',
    onSuccess: (r) => setConv(r.conversions),
  })
  const addConv = useAction(() => storePut<{ uom: string; to_base_factor: string }>('masters', `/items/${item.id}/conversions/${encodeURIComponent(add.uom.trim())}`, { to_base_factor: add.factor }), {
    invalidate: [...mastersInvalidate],
    success: 'Unit saved',
    onSuccess: (r) => {
      setConv((c) => [...c.filter((x) => x.uom.toLowerCase() !== r.uom.toLowerCase()), { uom: r.uom, to_base_factor: r.to_base_factor }])
      setAdd({ uom: '', factor: '' })
    },
  })
  const dropConv = useAction((uom: string) => storeDelete<{ message: string }>('masters', `/items/${item.id}/conversions/${encodeURIComponent(uom)}`), {
    invalidate: [...mastersInvalidate],
    onSuccess: (_r, uom) => setConv((c) => c.filter((x) => x.uom !== uom)),
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={item.name} description={`${item.code}. In the item master it is counted in ${item.item_uom || 'no unit'}. ${Number(item.on_hand).toLocaleString('en-IN')} on hand in the stores you can see.`}>
      <form onSubmit={(e) => { e.preventDefault(); if (canEdit) save.mutate() }}>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Category" htmlFor="im-cat">
            <Select id="im-cat" disabled={!canEdit} value={s.category} onChange={(e) => set('category', e.target.value)} options={(meta.data?.item_categories ?? [s.category]).map((c) => ({ value: c, label: c }))} />
          </Field>
          <Field label="Base unit" htmlFor="im-base" hint="Stock is counted and valued in this. It cannot change once stock has moved."><Input id="im-base" disabled={!canEdit} value={s.base_uom} onChange={(e) => set('base_uom', e.target.value)} maxLength={20} /></Field>
          <Field label="Over-receipt tolerance %" htmlFor="im-tol" hint="How far over the order a delivery may be."><Input id="im-tol" inputMode="decimal" disabled={!canEdit} value={s.over_receipt_tolerance_pct} onChange={(e) => set('over_receipt_tolerance_pct', e.target.value)} /></Field>
          <Field label="Reorder level" htmlFor="im-reorder"><Input id="im-reorder" inputMode="decimal" disabled={!canEdit} value={s.reorder_level} onChange={(e) => set('reorder_level', e.target.value)} /></Field>
          <Field label="Minimum" htmlFor="im-min"><Input id="im-min" inputMode="decimal" disabled={!canEdit} value={s.min_qty} onChange={(e) => set('min_qty', e.target.value)} /></Field>
          <Field label="Maximum" htmlFor="im-max" hint="Zero means no maximum."><Input id="im-max" inputMode="decimal" disabled={!canEdit} value={s.max_qty} onChange={(e) => set('max_qty', e.target.value)} /></Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-5 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" disabled={!canEdit} checked={s.qc_required} onChange={(e) => set('qc_required', e.target.checked)} /> Quality check needed on receipt</label>
          <label className="flex items-center gap-2"><input type="checkbox" disabled={!canEdit} checked={s.is_batch_tracked} onChange={(e) => set('is_batch_tracked', e.target.checked)} /> Tracked by batch</label>
        </div>
        {canEdit && <div className="mt-4 flex justify-end"><Button type="submit" loading={save.isPending} disabled={!s.base_uom.trim()}>Save settings</Button></div>}
      </form>
      <section aria-labelledby="im-conv" className="mt-6">
        <h3 id="im-conv" className="mb-2 border-b pb-1 text-sm font-semibold">Other units</h3>
        <p className="mb-2 text-xs text-muted-foreground">One of these units equals this many {s.base_uom || 'base units'}: for example 1 bag = 50 kg. Documents are entered in any of them and stored in {s.base_uom || 'the base unit'}.</p>
        {conv.length === 0 ? <p className="text-sm text-muted-foreground">No other units.</p> : (
          <ul className="divide-y rounded-lg border">
            {conv.map((c) => (
              <li key={c.uom} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                <span>1 <span className="font-medium">{c.uom}</span> = {Number(c.to_base_factor)} {s.base_uom}</span>
                {canEdit && <Button size="sm" variant="ghost" aria-label={`Remove ${c.uom}`} onClick={() => dropConv.mutate(c.uom)}>Remove</Button>}
              </li>
            ))}
          </ul>
        )}
        {canEdit && (
          <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (add.uom.trim() && add.factor) addConv.mutate() }}>
            <Field label="Unit" htmlFor="im-cu" className="w-32"><Input id="im-cu" value={add.uom} onChange={(e) => setAdd({ ...add, uom: e.target.value })} placeholder="bag" maxLength={20} /></Field>
            <Field label={`Equals (${s.base_uom || 'base'})`} htmlFor="im-cf" className="w-40"><Input id="im-cf" inputMode="decimal" value={add.factor} onChange={(e) => setAdd({ ...add, factor: e.target.value })} placeholder="50" /></Field>
            <Button type="submit" variant="outline" loading={addConv.isPending} disabled={!add.uom.trim() || !add.factor}>Add unit</Button>
          </form>
        )}
      </section>
    </Modal>
  )
}
