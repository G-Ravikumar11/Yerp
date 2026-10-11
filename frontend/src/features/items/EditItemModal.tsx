import { useState } from 'react'
import { Button, Field, Input, Modal, Select, Textarea } from '@/components/ui'
import { itemKeys, updateItem, type Item, type ItemVocabulary } from '@/api/items'
import { useAction } from '@/lib/mutate'

/** One item's particulars. Its code is fixed: work orders and budgets already refer to it. */
export function EditItemModal({ item, onClose, vocab }: { item: Item | null; onClose: () => void; vocab: ItemVocabulary | undefined }) {
  return (
    <Modal open={!!item} onOpenChange={(o) => !o && onClose()} title={item ? `${item.item_code} - ${item.item_name}` : 'Item'} description="The code cannot be changed once issued." size="md">
      {item && <EditForm key={item.id} item={item} onClose={onClose} vocab={vocab} />}
    </Modal>
  )
}

function EditForm({ item, onClose, vocab }: { item: Item; onClose: () => void; vocab: ItemVocabulary | undefined }) {
  const [f, setF] = useState({
    item_name: item.item_name,
    description: item.description === item.item_name ? '' : item.description,
    item_type: item.item_type,
    units_of_measure: item.units_of_measure,
    hsn_code: item.hsn_code,
    item_tax_type: item.item_tax_type,
    reorder_level: item.reorder_level ? String(item.reorder_level) : '',
  })
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }))

  const save = useAction(
    () =>
      updateItem(item.id, {
        kind: item.kind,
        ...f,
        reorder_level: f.reorder_level === '' ? 0 : Number(f.reorder_level),
      }),
    { invalidate: [itemKeys.all], onSuccess: onClose },
  )

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
      className="grid gap-4 sm:grid-cols-2"
    >
      <Field label="Name" htmlFor="ei-name" className="sm:col-span-2">
        <Input id="ei-name" value={f.item_name} onChange={set('item_name')} required autoFocus />
      </Field>
      <Field label="Description" htmlFor="ei-desc" hint="Left blank, it is the name." className="sm:col-span-2">
        <Textarea id="ei-desc" value={f.description} onChange={set('description')} />
      </Field>
      <Field label="Type" htmlFor="ei-type">
        <Select id="ei-type" value={f.item_type} onChange={set('item_type')} options={(vocab?.item_types ?? [f.item_type]).map((v) => ({ value: v, label: v }))} />
      </Field>
      <Field label="Unit" htmlFor="ei-unit">
        <Select id="ei-unit" value={f.units_of_measure} onChange={set('units_of_measure')} options={(vocab?.units ?? [f.units_of_measure]).map((v) => ({ value: v, label: v }))} />
      </Field>
      <Field label="HSN / SAC" htmlFor="ei-hsn">
        <Input id="ei-hsn" value={f.hsn_code} onChange={set('hsn_code')} className="font-mono" />
      </Field>
      <Field label="Tax" htmlFor="ei-tax">
        <Select id="ei-tax" value={f.item_tax_type} onChange={set('item_tax_type')} options={(vocab?.tax_rates ?? [f.item_tax_type]).map((v) => ({ value: v, label: v }))} />
      </Field>
      <Field label="Reorder level" htmlFor="ei-reorder" hint="The store warns when stock falls below this." className="sm:col-span-2">
        <Input id="ei-reorder" type="number" min={0} step="any" value={f.reorder_level} onChange={set('reorder_level')} />
      </Field>
      <div className="flex justify-end gap-2 sm:col-span-2">
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={save.isPending}>
          Save
        </Button>
      </div>
    </form>
  )
}
