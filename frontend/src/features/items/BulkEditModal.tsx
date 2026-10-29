import { useState } from 'react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { bulkUpdate, masterKeys, useCategories, type BulkChange, type Gap } from '@/api/itemMaster'
import { itemKeys, type ItemVocabulary } from '@/api/items'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'
import { GST_RATES, orderUnits } from './itemLogic'

const LEAVE = '__leave__'
const NONE = '__none__'

/**
 * The same details filled in on every ticked item at once - how the gaps in an imported list get closed. Each field
 * starts at "leave as it is", so only what is chosen here changes; nothing else on the items moves.
 */
export function BulkEditModal({ open, onOpenChange, ids, focus, vocab, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; ids: number[]; focus: Gap | ''; vocab: ItemVocabulary | undefined; onDone: () => void }) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} size="lg" title={`Edit ${ids.length} item${ids.length === 1 ? '' : 's'} together`}
      description="Only what you change here is changed on each item. Everything left at “Leave as it is” stays as it was.">
      {open && <Form ids={ids} focus={focus} vocab={vocab} onClose={() => onOpenChange(false)} onDone={onDone} />}
    </Modal>
  )
}

function Form({ ids, focus, vocab, onClose, onDone }: { ids: number[]; focus: Gap | ''; vocab: ItemVocabulary | undefined; onClose: () => void; onDone: () => void }) {
  const cats = useCategories()
  const [kind, setKind] = useState(LEAVE)
  const [cat, setCat] = useState(LEAVE)
  const [sub, setSub] = useState('')
  const [gst, setGst] = useState(LEAVE)
  const [unit, setUnit] = useState(LEAVE)
  const [type, setType] = useState(LEAVE)
  const [hsn, setHsn] = useState('')
  const [make, setMake] = useState('')
  const subs = cats.data?.find((c) => c.name === cat)?.subcategories.filter((s) => s.is_active) ?? []
  const leave = { value: LEAVE, label: 'Leave as it is' }

  const change: BulkChange = {}
  if (kind !== LEAVE) change.kind = kind as 'RM' | 'FG'
  if (cat !== LEAVE) { change.item_category = cat === NONE ? '' : cat; change.item_subcategory = cat === NONE ? '' : sub }
  if (gst !== LEAVE) change.gst_percent = Number(gst)
  if (unit !== LEAVE) change.units_of_measure = unit
  if (type !== LEAVE) change.item_type = type
  if (hsn.trim()) change.hsn_code = hsn.trim()
  if (make.trim()) change.make = make.trim()
  const what = [change.kind && 'what it is', cat !== LEAVE && 'category', change.gst_percent !== undefined && 'GST', change.hsn_code && 'HSN / SAC', change.make && 'make', change.units_of_measure && 'unit', change.item_type && 'type'].filter(Boolean) as string[]
  const save = useAction(() => bulkUpdate(ids, change), { invalidate: [masterKeys.all, itemKeys.all], onSuccess: () => { onDone(); onClose() } })
  // The detail the person came to fill in comes first and is the one to look at.
  const ring = (g: Gap) => (focus === g ? 'rounded-lg ring-2 ring-primary/40 ring-offset-4 ring-offset-popover' : '')

  return (
    <div className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Category" htmlFor="be-cat" className={ring('category')}>
          <Select id="be-cat" value={cat} onChange={(e) => { setCat(e.target.value); setSub('') }}
            options={[leave, { value: NONE, label: 'No category' }, ...(cats.data ?? []).filter((c) => c.is_active).map((c) => ({ value: c.name, label: c.name }))]} />
        </Field>
        <Field label="Subcategory" htmlFor="be-sub">
          <Select id="be-sub" value={sub} disabled={!subs.length} placeholder={subs.length ? 'No subcategory' : cat === LEAVE ? 'Choose a category first' : 'None set up'} onChange={(e) => setSub(e.target.value)} options={subs.map((s) => ({ value: s.name, label: s.name }))} />
        </Field>
        <Field label="GST (tax) rate" htmlFor="be-gst" className={ring('gst')}>
          <Select id="be-gst" value={gst} onChange={(e) => setGst(e.target.value)} options={[leave, ...GST_RATES.map((r) => ({ value: r, label: `${r}%` }))]} />
        </Field>
        <Field label="HSN / SAC code" htmlFor="be-hsn" className={ring('hsn')}>
          <Input id="be-hsn" className="font-mono" value={hsn} onChange={(e) => setHsn(e.target.value)} placeholder="Leave as it is" />
        </Field>
        <Field label="Make" htmlFor="be-make" hint="The brand, for materials: UltraTech, Tata Tiscon, Finolex." className={ring('make')}>
          <Input id="be-make" value={make} onChange={(e) => setMake(e.target.value)} placeholder="Leave as it is" />
        </Field>
        <Field label="Unit" htmlFor="be-unit">
          <Select id="be-unit" value={unit} onChange={(e) => setUnit(e.target.value)} options={[leave, ...orderUnits(vocab?.units ?? []).map((u) => ({ value: u, label: u }))]} />
        </Field>
        <Field label="What it is" htmlFor="be-kind" hint="Only for items nothing uses yet.">
          <Select id="be-kind" value={kind} onChange={(e) => setKind(e.target.value)} options={[leave, { value: 'RM', label: 'Material (bought and kept in stock)' }, { value: 'FG', label: 'Work item (on BOQs and work orders)' }]} />
        </Field>
        <Field label="Item type" htmlFor="be-type">
          <Select id="be-type" value={type} onChange={(e) => setType(e.target.value)} options={[leave, ...(vocab?.boq_item_types ?? []).map((v) => ({ value: v, label: v }))]} />
        </Field>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error ? <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>
          : <p className={cn('mr-auto text-[13px]', what.length ? 'text-foreground' : 'text-muted-foreground')}>{what.length ? `Changes the ${what.join(', ')} of ${ids.length} item${ids.length === 1 ? '' : 's'}.` : 'Nothing chosen to change yet.'}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!what.length} onClick={() => save.mutate()}>Save changes</Button>
      </div>
    </div>
  )
}
