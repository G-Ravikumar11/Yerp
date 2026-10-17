import { useEffect, useState } from 'react'
import { Search, Trash2 } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Field, Input, Modal, Select } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { storeKeys, storePerm } from '@/api/store'
import {
  addPreset, addUom, deleteUom, mastersKeys, saveSettings, updateUom, useMasterItem, useMasterItems, type ItemRow, type ItemSettings,
} from './api'

const refresh = { invalidate: [mastersKeys.all, storeKeys.all] }
const CATEGORIES = ['CONSUMABLE', 'RETURNABLE', 'TOOL', 'SPARE'] as const
const CATEGORY_LABEL: Record<string, string> = { CONSUMABLE: 'Consumable', RETURNABLE: 'Returnable', TOOL: 'Tool', SPARE: 'Spare' }

/** Masters > Items & units: what the store keeps for each stock item, and the units it can be counted in. */
export function ItemsTab() {
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  const [configured, setConfigured] = useState('')
  const [open, setOpen] = useState<number | null>(null)
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 250)
    return () => clearTimeout(t)
  }, [text])
  const items = useMasterItems(q, configured)
  const cols: TableColumn<ItemRow>[] = [
    { id: 'item', header: 'Item', sort: (r) => r.name, cell: (r) => <div><span className="font-mono text-xs text-muted-foreground">{r.code}</span> {r.name}</div> },
    { id: 'cat', header: 'Store category', width: '9rem', hideBelow: 'md', cell: (r) => (r.settings ? CATEGORY_LABEL[r.settings.category] ?? r.settings.category : <Badge tone="warning">Not set up</Badge>) },
    { id: 'base', header: 'Base unit', width: '6rem', cell: (r) => r.base_uom },
    { id: 'uoms', header: 'Also counted in', hideBelow: 'md', cell: (r) => r.uoms.filter((u) => !u.base).map((u) => `${u.code} (${Number(u.to_base_factor)} ${r.base_uom})`).join(', ') || '-' },
    { id: 'reorder', header: 'Reorder at', align: 'right', width: '7rem', hideBelow: 'lg', cell: (r) => (r.settings ? Number(r.settings.reorder_level) || '-' : '-') },
  ]
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-full max-w-sm"><Input leading={<Search />} aria-label="Search items" placeholder="Search item code or name" value={text} onChange={(e) => setText(e.target.value)} /></div>
        <div className="w-44">
          <Select aria-label="Set up" value={configured} options={[{ value: '', label: 'All items' }, { value: 'no', label: 'Not set up yet' }, { value: 'yes', label: 'Set up' }]} onChange={(e) => setConfigured(e.target.value)} />
        </div>
      </div>
      <DataTable label="Stock items" rows={items.data ?? []} columns={cols} rowKey={(r) => r.id} loading={items.isPending} onRowClick={(r) => setOpen(r.id)} empty="No stock items. Items come from the Item Master (raw materials)." />
      {open && <ItemModal itemId={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

function blank(item: ItemRow): ItemSettings {
  return item.settings ?? {
    category: 'CONSUMABLE', base_uom: item.base_uom || item.item_uom, reorder_level: '0', min_qty: '0', max_qty: '0', qc_required: false,
    over_receipt_tolerance_pct: '0', is_batch_tracked: false,
  }
}

function ItemModal({ itemId, onClose }: { itemId: number; onClose: () => void }) {
  const { can } = useSession()
  const manage = can(storePerm('masters', 'create'))
  const item = useMasterItem(itemId)
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={item.data ? `${item.data.code} - ${item.data.name}` : 'Item'} description="Store settings and units">
      {item.data ? (
        <div className="space-y-6">
          <SettingsForm key={JSON.stringify(item.data.settings)} item={item.data} manage={manage} />
          <Units item={item.data} manage={manage} />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Loading...</p>
      )}
    </Modal>
  )
}

const qtyOk = (s: string) => /^\d*\.?\d{0,3}$/.test(s)

function SettingsForm({ item, manage }: { item: ItemRow; manage: boolean }) {
  const [f, setF] = useState<ItemSettings>(blank(item))
  const save = useAction(() => saveSettings(item.id, f), { ...refresh, success: 'Settings saved.' })
  const num = (key: 'reorder_level' | 'min_qty' | 'max_qty' | 'over_receipt_tolerance_pct', label: string) => (
    <Field label={label} htmlFor={`set-${key}`}>
      <Input id={`set-${key}`} inputMode="decimal" className="text-right" disabled={!manage} value={f[key]} onChange={(e) => qtyOk(e.target.value) && setF({ ...f, [key]: e.target.value })} />
    </Field>
  )
  return (
    <section>
      <h3 className="mb-3 text-sm font-semibold">Store settings</h3>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Category" htmlFor="set-cat">
          <Select id="set-cat" disabled={!manage} value={f.category} options={CATEGORIES.map((c) => ({ value: c, label: CATEGORY_LABEL[c] }))} onChange={(e) => setF({ ...f, category: e.target.value })} />
        </Field>
        <Field label="Base unit" htmlFor="set-base" hint={item.has_stock_history ? 'Fixed: stock is already counted in it.' : 'What stock is counted and valued in.'}>
          <Input id="set-base" disabled={!manage || item.has_stock_history} value={f.base_uom} onChange={(e) => setF({ ...f, base_uom: e.target.value.trim() })} />
        </Field>
        {num('reorder_level', `Reorder level (${f.base_uom})`)}
        {num('min_qty', 'Minimum')}
        {num('max_qty', 'Maximum')}
        {num('over_receipt_tolerance_pct', 'Over-receipt tolerance %')}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-5 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" disabled={!manage} checked={f.qc_required} onChange={(e) => setF({ ...f, qc_required: e.target.checked })} /> Quality check on receipt</label>
        <label className="flex items-center gap-2"><input type="checkbox" disabled={!manage} checked={f.is_batch_tracked} onChange={(e) => setF({ ...f, is_batch_tracked: e.target.checked })} /> Batch tracked</label>
        {manage && <Button className="ml-auto" loading={save.isPending} onClick={() => save.mutate()}>{item.configured ? 'Save settings' : 'Set up item'}</Button>}
      </div>
    </section>
  )
}

function Units({ item, manage }: { item: ItemRow; manage: boolean }) {
  const [code, setCode] = useState('')
  const [factor, setFactor] = useState('')
  const [dia, setDia] = useState('12')
  const [length, setLength] = useState('12')
  const add = useAction(() => addUom(item.id, { from_uom: code, to_base_factor: factor }), { ...refresh, success: 'Unit added.', onSuccess: () => { setCode(''); setFactor('') } })
  const preset = useAction((kind: 'CEMENT' | 'STEEL' | 'VOLUME') => addPreset(item.id, kind === 'STEEL' ? { kind, dia_mm: dia, bar_length_m: length } : { kind }), { ...refresh, success: 'Standard units set.' })
  const change = useAction((v: { id: number; factor: string }) => updateUom(v.id, v.factor), { ...refresh, success: false })
  const remove = useAction((id: number) => deleteUom(id), { ...refresh, success: 'Unit removed.' })
  const base = item.base_uom.toLowerCase()
  const kgPerBar = Number(dia) > 0 && Number(length) > 0 ? ((Number(dia) ** 2 / 162) * Number(length)).toFixed(3) : null
  return (
    <section>
      <h3 className="mb-1 text-sm font-semibold">Units</h3>
      <p className="mb-3 text-xs text-muted-foreground">Stock is always posted in {item.base_uom}. Any other unit is converted: 1 unit = factor x {item.base_uom}.</p>
      <DataTable
        label="Units"
        rows={item.uoms}
        rowKey={(u) => u.id ?? 'base'}
        columns={[
          { id: 'code', header: 'Unit', width: '8rem', cell: (u) => <span className="font-medium">{u.code}{u.base && <span className="ml-2 text-xs text-muted-foreground">base</span>}</span> },
          {
            id: 'f',
            header: `In ${item.base_uom}`,
            align: 'right',
            cell: (u) =>
              u.base || !manage ? (
                Number(u.to_base_factor)
              ) : (
                <FactorCell value={u.to_base_factor} onSave={(v) => u.id && change.mutate({ id: u.id, factor: v })} />
              ),
          },
          { id: 'x', header: '', align: 'right', width: '3rem', cell: (u) => manage && !u.base && u.id && <Button size="icon-sm" variant="ghost" aria-label={`Remove ${u.code}`} onClick={() => remove.mutate(u.id as number)}><Trash2 /></Button> },
        ]}
      />
      {manage && (
        <div className="mt-4 space-y-4">
          <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (code && factor) add.mutate() }}>
            <Field label="Unit" htmlFor="uom-code" className="w-28"><Input id="uom-code" value={code} onChange={(e) => setCode(e.target.value.trim())} placeholder="bag" /></Field>
            <Field label={`= how many ${item.base_uom}`} htmlFor="uom-f" className="w-36"><Input id="uom-f" inputMode="decimal" className="text-right" value={factor} onChange={(e) => /^\d*\.?\d{0,6}$/.test(e.target.value) && setFactor(e.target.value)} placeholder="50" /></Field>
            <Button type="submit" variant="outline" loading={add.isPending} disabled={!code || !factor}>Add unit</Button>
          </form>
          <div className="rounded-lg border border-border p-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Standard sets</p>
            <div className="flex flex-wrap items-end gap-2">
              {['kg', 'bag', 'mt'].includes(base) && <Button size="sm" variant="soft" loading={preset.isPending && preset.variables === 'CEMENT'} onClick={() => preset.mutate('CEMENT')}>Cement: kg / bag (50 kg) / MT</Button>}
              {['cum', 'cft'].includes(base) && <Button size="sm" variant="soft" loading={preset.isPending && preset.variables === 'VOLUME'} onClick={() => preset.mutate('VOLUME')}>Volume: cum / cft</Button>}
              {['kg', 'mt'].includes(base) && (
                <>
                  <Field label="Bar dia (mm)" htmlFor="st-dia" className="w-28"><Input id="st-dia" inputMode="decimal" value={dia} onChange={(e) => /^\d*\.?\d*$/.test(e.target.value) && setDia(e.target.value)} /></Field>
                  <Field label="Bar length (m)" htmlFor="st-len" className="w-28"><Input id="st-len" inputMode="decimal" value={length} onChange={(e) => /^\d*\.?\d*$/.test(e.target.value) && setLength(e.target.value)} /></Field>
                  <Button size="sm" variant="soft" disabled={!kgPerBar} loading={preset.isPending && preset.variables === 'STEEL'} onClick={() => preset.mutate('STEEL')}>Steel: nos / MT</Button>
                  {kgPerBar && <span className="pb-2 text-xs text-muted-foreground">d&sup2;/162 x {length} m = {kgPerBar} kg a bar</span>}
                </>
              )}
              {!['kg', 'bag', 'mt', 'cum', 'cft'].includes(base) && <span className="text-xs text-muted-foreground">No standard set for {item.base_uom}; add units by hand.</span>}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

function FactorCell({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [v, setV] = useState(String(Number(value)))
  return (
    <Input
      aria-label="Factor"
      inputMode="decimal"
      className="ml-auto h-8 w-32 text-right"
      value={v}
      onChange={(e) => /^\d*\.?\d{0,6}$/.test(e.target.value) && setV(e.target.value)}
      onBlur={() => Number(v) > 0 && Number(v) !== Number(value) && onSave(v)}
      onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
    />
  )
}
