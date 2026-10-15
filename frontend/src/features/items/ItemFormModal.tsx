import { useState } from 'react'
import { Button, Field, Input, Modal, Select, Textarea } from '@/components/ui'
import { createMasterItem, masterKeys, updateMasterItem, useCategories, useItemSites, type MasterItem } from '@/api/itemMaster'
import { itemKeys, type ItemVocabulary } from '@/api/items'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'

export type FormMode = 'create' | 'edit' | 'view' | 'duplicate'

const num = (v: string) => (v.trim() === '' ? null : Number(v))
const text = (n: number | null | undefined) => (n ? String(n) : '')
const gstOf = (tax: string) => (tax ? String(parseFloat(tax)) : '')

/** One item, to read, make, change or copy. A copy starts without a code, so it is issued its own. */
export function ItemFormModal({ item, mode, onClose, vocab }: { item: MasterItem | null; mode: FormMode | null; onClose: () => void; vocab: ItemVocabulary | undefined }) {
  const open = mode !== null
  const title = mode === 'create' ? 'New item' : mode === 'duplicate' ? 'Duplicate item' : item ? `${item.item_code} - ${item.item_name}` : 'Item'
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={title} size="lg"
      description={mode === 'edit' ? 'The code cannot be changed once issued: orders and BOQ lines already refer to it.' : mode === 'view' ? undefined : 'Leave the code blank to be issued the next one.'}>
      {open && <Form key={`${mode}-${item?.id ?? 'new'}`} item={item} mode={mode} onClose={onClose} vocab={vocab} />}
    </Modal>
  )
}

function Form({ item, mode, onClose, vocab }: { item: MasterItem | null; mode: FormMode; onClose: () => void; vocab: ItemVocabulary | undefined }) {
  const readonly = mode === 'view'
  const cats = useCategories()
  const sites = useItemSites(mode === 'view' && item ? item.id : null)
  const base = item
  const [f, setF] = useState({
    item_code: mode === 'duplicate' ? '' : (base?.item_code ?? ''),
    item_name: base?.item_name ?? '',
    description: base && base.description !== base.item_name ? base.description : '',
    item_category: base?.item_category ?? '',
    item_subcategory: base?.item_subcategory ?? '',
    item_type: base?.item_type ?? 'Work',
    units_of_measure: base?.units_of_measure ?? 'Nos',
    specification: base?.specification ?? '',
    purchase_rate: text(base?.purchase_rate),
    selling_rate: text(base?.selling_rate),
    hsn_code: base?.hsn_code ?? '',
    gst_percent: gstOf(base?.item_tax_type ?? ''),
    preferred_supplier: base?.preferred_supplier ?? '',
    reorder_level: text(base?.reorder_level),
    remarks: base?.remarks ?? '',
    is_active: base?.is_active ?? true,
  })
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  const subs = cats.data?.find((c) => c.name === f.item_category)?.subcategories.filter((s) => s.is_active) ?? []

  const body = () => ({
    ...f,
    purchase_rate: num(f.purchase_rate),
    selling_rate: num(f.selling_rate),
    gst_percent: num(f.gst_percent),
    reorder_level: num(f.reorder_level),
  })
  const save = useAction(() => (mode === 'edit' && item ? updateMasterItem(item.id, body()) : createMasterItem(body())), {
    invalidate: [masterKeys.all, itemKeys.all],
    onSuccess: onClose,
  })
  const fixed = readonly
  const types = vocab?.boq_item_types ?? ['Work']

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!readonly) save.mutate()
      }}
      className="grid gap-4 sm:grid-cols-2"
    >
      <Field label="Item code" htmlFor="im-code" hint={mode === 'edit' ? undefined : 'Letters, numbers and - _ / . up to 30. Blank: issued automatically.'}>
        <Input id="im-code" className="font-mono uppercase" value={f.item_code} onChange={set('item_code')} disabled={fixed || mode === 'edit'} maxLength={30} placeholder="Automatic" />
      </Field>
      <Field label="Item name" htmlFor="im-name">
        <Input id="im-name" value={f.item_name} onChange={set('item_name')} required disabled={fixed} autoFocus={!readonly} />
      </Field>
      <Field label="Detailed description" htmlFor="im-desc" className="sm:col-span-2" hint="Left blank, it is the name.">
        <Textarea id="im-desc" value={f.description} onChange={set('description')} disabled={fixed} />
      </Field>
      <Field label="Category" htmlFor="im-cat">
        <Select id="im-cat" value={f.item_category} disabled={fixed} placeholder="No category"
          onChange={(e) => setF((s) => ({ ...s, item_category: e.target.value, item_subcategory: '' }))}
          options={(cats.data ?? []).filter((c) => c.is_active || c.name === f.item_category).map((c) => ({ value: c.name, label: c.name }))} />
      </Field>
      <Field label="Subcategory" htmlFor="im-sub">
        <Select id="im-sub" value={f.item_subcategory} disabled={fixed || !subs.length} placeholder={subs.length ? 'No subcategory' : 'None set up'} onChange={set('item_subcategory')}
          options={subs.map((s) => ({ value: s.name, label: s.name }))} />
      </Field>
      <Field label="Item type" htmlFor="im-type">
        <Select id="im-type" value={f.item_type} disabled={fixed} onChange={set('item_type')} options={types.map((v) => ({ value: v, label: v }))} />
      </Field>
      <Field label="Unit of measurement" htmlFor="im-uom">
        <Select id="im-uom" value={f.units_of_measure} disabled={fixed} onChange={set('units_of_measure')} options={(vocab?.units ?? [f.units_of_measure]).map((v) => ({ value: v, label: v }))} />
      </Field>
      <Field label="Material / grade / specification" htmlFor="im-spec" className="sm:col-span-2">
        <Input id="im-spec" value={f.specification} onChange={set('specification')} disabled={fixed} placeholder="M25, Fe550D, 53 grade OPC" />
      </Field>
      <Field label="Default purchase rate" htmlFor="im-prate" hint="Optional.">
        <Input id="im-prate" type="number" min={0} step="any" value={f.purchase_rate} onChange={set('purchase_rate')} disabled={fixed} />
      </Field>
      <Field label="Default selling rate" htmlFor="im-srate" hint="A default only. Each site has its own finalised rate.">
        <Input id="im-srate" type="number" min={0} step="any" value={f.selling_rate} onChange={set('selling_rate')} disabled={fixed} />
      </Field>
      <Field label="HSN / SAC code" htmlFor="im-hsn">
        <Input id="im-hsn" className="font-mono" value={f.hsn_code} onChange={set('hsn_code')} disabled={fixed} />
      </Field>
      <Field label="GST %" htmlFor="im-gst">
        <Input id="im-gst" type="number" min={0} max={100} step="any" value={f.gst_percent} onChange={set('gst_percent')} disabled={fixed} />
      </Field>
      <Field label="Preferred supplier" htmlFor="im-sup">
        <Input id="im-sup" value={f.preferred_supplier} onChange={set('preferred_supplier')} disabled={fixed} />
      </Field>
      <Field label="Minimum stock level" htmlFor="im-min">
        <Input id="im-min" type="number" min={0} step="any" value={f.reorder_level} onChange={set('reorder_level')} disabled={fixed} />
      </Field>
      <Field label="Remarks" htmlFor="im-rem" className="sm:col-span-2">
        <Textarea id="im-rem" value={f.remarks} onChange={set('remarks')} disabled={fixed} />
      </Field>
      {!readonly && (
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input type="checkbox" checked={f.is_active} onChange={(e) => setF((s) => ({ ...s, is_active: e.target.checked }))} /> Active
        </label>
      )}

      {readonly && item && (
        <div className="sm:col-span-2">
          <p className="mb-2 text-sm font-medium">Sites using this item ({sites.data?.sites.length ?? item.sites})</p>
          {sites.data?.sites.length ? (
            <ul className="divide-y rounded-md border text-sm">
              {sites.data.sites.map((s) => (
                <li key={s.site_id} className="flex flex-wrap justify-between gap-2 px-3 py-2">
                  <span>{s.site_code} {s.site_name}</span>
                  <span className="text-muted-foreground">
                    qty {s.quantity} · {s.site_rate === null ? 'rate pending' : `${formatINR(s.site_rate)} (${s.status})`}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No site's BOQ uses it yet.</p>
          )}
          <p className="mt-3 text-xs text-muted-foreground">
            Added by {item.created_by || '-'} {item.created_at} · last changed by {item.updated_by || '-'} {item.updated_at}
          </p>
        </div>
      )}

      <div className="flex justify-end gap-2 sm:col-span-2">
        <Button type="button" variant="ghost" onClick={onClose}>
          {readonly ? 'Close' : 'Cancel'}
        </Button>
        {!readonly && (
          <Button type="submit" loading={save.isPending}>
            {mode === 'edit' ? 'Save changes' : 'Add item'}
          </Button>
        )}
      </div>
    </form>
  )
}
