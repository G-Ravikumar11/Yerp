import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, TriangleAlert } from 'lucide-react'
import { Button, Field, Input, Modal, Select, Textarea } from '@/components/ui'
import { createMasterItem, fetchNextCode, fetchSimilar, masterKeys, updateMasterItem, useCategories, type MasterItem, type MasterItemInput } from '@/api/itemMaster'
import { itemKeys, type ItemVocabulary } from '@/api/items'
import { useAction } from '@/lib/mutate'
import { useDebounced } from '@/lib/hooks'
import { GST_RATES, defaultTypeFor, matchUnit, orderUnits, validateItem, type ItemErrors, type ItemForm } from './itemLogic'
import { MoneyInput } from './MoneyInput'

export type FormMode = 'create' | 'edit' | 'duplicate'

const text = (n: number | null | undefined) => (n ? String(n) : '')
const gstOf = (tax: string) => (tax && Number.isFinite(parseFloat(tax)) ? String(parseFloat(tax)) : '')
const num = (v: string) => (v.trim() === '' ? null : Number(v))

/** One item, to read, make, change or copy. A copy starts with the next free code, so it is its own item. */
export function ItemFormModal({ item, mode, onClose, vocab, onOpenItem }: { item: MasterItem | null; mode: FormMode | null; onClose: () => void; vocab: ItemVocabulary | undefined; onOpenItem?: (id: number) => void }) {
  const open = mode !== null
  // After "Save and add another" the form starts again, keeping what the next item will probably share.
  const [round, setRound] = useState(0)
  const [carry, setCarry] = useState<Partial<ItemForm>>({})
  const title = mode === 'create' ? 'New item' : mode === 'duplicate' ? 'Copy as a new item' : item ? item.item_name : 'Item'
  const describe = mode === 'edit' ? `Code ${item?.item_code}. A code cannot be changed once it is in use on a BOQ, order or bill.` : 'Fill in the basics; everything else is optional.'
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={title} description={describe} size="lg">
      {open && (
        <Form key={`${mode}-${item?.id ?? 'new'}-${round}`} item={item} mode={mode} carry={carry} vocab={vocab} onClose={onClose} onOpenItem={onOpenItem}
          onAnother={(keep) => { setCarry(keep); setRound((r) => r + 1) }} />
      )}
    </Modal>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-4 sm:grid-cols-2">
      <h3 className="border-b pb-1 text-sm font-semibold sm:col-span-2">{title}</h3>
      {children}
    </section>
  )
}

function Form({ item, mode, carry, vocab, onClose, onOpenItem, onAnother }: {
  item: MasterItem | null
  mode: FormMode
  carry: Partial<ItemForm>
  vocab: ItemVocabulary | undefined
  onClose: () => void
  onOpenItem?: (id: number) => void
  onAnother: (keep: Partial<ItemForm>) => void
}) {
  const editing = mode === 'edit'
  const cats = useCategories()
  const base = mode === 'create' ? null : item
  const units = useMemo(() => orderUnits(vocab?.units ?? []), [vocab])
  const [f, setF] = useState<ItemForm>({
    item_code: mode === 'duplicate' ? '' : (base?.item_code ?? ''),
    item_name: mode === 'duplicate' ? `${base?.item_name ?? ''} (copy)` : (base?.item_name ?? ''),
    kind: base?.kind ?? carry.kind ?? 'FG',
    units_of_measure: base?.units_of_measure ?? carry.units_of_measure ?? '',
    item_category: base?.item_category ?? carry.item_category ?? '',
    item_subcategory: base?.item_subcategory ?? carry.item_subcategory ?? '',
    specification: base?.specification ?? '',
    purchase_rate: text(base?.purchase_rate),
    selling_rate: text(base?.selling_rate),
    gst_percent: gstOf(base?.item_tax_type ?? '') || carry.gst_percent || '',
    hsn_code: base?.hsn_code ?? '',
    item_type: base?.item_type ?? carry.item_type ?? defaultTypeFor(base?.kind ?? carry.kind ?? 'FG'),
    preferred_supplier: base?.preferred_supplier ?? '',
    reorder_level: text(base?.reorder_level),
    description: base && base.description !== base.item_name ? base.description : '',
    remarks: base?.remarks ?? '',
    is_active: base?.is_active ?? true,
    make: base?.make ?? '',
    segment: base?.segment ?? '',
  })
  const set = <K extends keyof ItemForm>(k: K, v: ItemForm[K]) => setF((s) => ({ ...s, [k]: v }))
  const field = (k: keyof ItemForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => set(k, e.target.value as never)
  const [touched, setTouched] = useState<Set<keyof ItemForm>>(new Set())
  const [submitted, setSubmitted] = useState(false)
  const errors: ItemErrors = validateItem(f, units)
  const show = (k: keyof ItemForm) => (submitted || touched.has(k) ? errors[k] : undefined)
  const blur = (k: keyof ItemForm) => () => setTouched((t) => new Set(t).add(k))
  const hasMore = !!(f.hsn_code || f.preferred_supplier || f.reorder_level || f.description || f.remarks || f.segment || (editing && base && f.item_type !== defaultTypeFor(base.kind)))
  const [more, setMore] = useState(hasMore)
  const nameRef = useRef<HTMLInputElement>(null)

  // Start with the next free code. It is only a suggestion: type another to use your own scheme.
  const suggested = useQuery({ queryKey: ['item-master', 'next-code', mode, item?.id], queryFn: fetchNextCode, enabled: !editing, staleTime: 0, gcTime: 0 })
  const offered = useRef(false)
  useEffect(() => {
    if (!offered.current && suggested.data && !f.item_code) {
      offered.current = true
      set('item_code', suggested.data)
    }
  }, [suggested.data, f.item_code])

  // Look for a repeat while the name or code is being typed.
  const name = useDebounced(f.item_name, 350)
  const code = useDebounced(f.item_code, 350)
  const similar = useQuery({
    queryKey: ['item-master', 'similar', name, code, base?.id ?? 0],
    queryFn: () => fetchSimilar(name, code, editing ? item?.id : undefined),
    enabled: (name.trim().length >= 3 || code.trim().length >= 2),
  })
  const repeats = (similar.data ?? []).filter((s) => !(mode === 'duplicate' && s.id === item?.id && s.reason !== 'Same code'))
  const codeOwner = repeats.find((s) => s.reason === 'Same code')
  const nameRepeats = repeats.filter((s) => s.reason !== 'Same code')
  const subs = cats.data?.find((c) => c.name === f.item_category)?.subcategories.filter((s) => s.is_active) ?? []

  const body = (): MasterItemInput => ({
    item_code: f.item_code.trim(),
    item_name: f.item_name,
    kind: f.kind,
    description: f.description,
    item_category: f.item_category,
    item_subcategory: f.item_subcategory,
    item_type: f.item_type,
    units_of_measure: matchUnit(f.units_of_measure, units),
    specification: f.specification,
    purchase_rate: num(f.purchase_rate),
    selling_rate: num(f.selling_rate),
    hsn_code: f.hsn_code,
    gst_percent: num(f.gst_percent),
    preferred_supplier: f.preferred_supplier,
    reorder_level: num(f.reorder_level),
    remarks: f.remarks,
    is_active: f.is_active,
    make: f.make,
    segment: f.segment,
  })
  const save = useAction((_again: boolean) => (editing && item ? updateMasterItem(item.id, body()) : createMasterItem(body())), {
    invalidate: [masterKeys.all, itemKeys.all],
    onSuccess: (_r, again) => {
      if (again) onAnother({ kind: f.kind, units_of_measure: f.units_of_measure, item_category: f.item_category, item_subcategory: f.item_subcategory, item_type: f.item_type, gst_percent: f.gst_percent })
      else onClose()
    },
  })
  const submit = (again = false) => {
    setSubmitted(true)
    if (codeOwner && !editing) {
      document.getElementById('im-code')?.focus()
      return
    }
    if (Object.keys(errors).length) {
      // Take the person to the first thing to fix, opening the part it is in.
      if (errors.hsn_code || errors.reorder_level) setMore(true)
      requestAnimationFrame(() => document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus())
      return
    }
    save.mutate(again)
  }

  return (
    <form id="item-form" noValidate className="grid gap-6" onSubmit={(e) => { e.preventDefault(); submit(false) }}>
      <Section title="Basics">
        <div className="sm:col-span-2" role="radiogroup" aria-label="What is it?">
          <span className="mb-1.5 block text-sm font-medium">What is it?{editing && <span className="ml-2 text-xs font-normal text-muted-foreground">Can change only while nothing uses the item yet.</span>}</span>
          <div className="grid gap-2 sm:grid-cols-2">
            {([['RM', 'Material', 'Bought and kept in the store: cement, steel, sand.'], ['FG', 'Work item', 'Used on BOQ lines and work orders: PCC, plastering, shuttering.']] as const).map(([k, label, hint]) => (
              <button key={k} type="button" role="radio" aria-checked={f.kind === k}
                className={`rounded-lg border p-3 text-left text-sm ${f.kind === k ? 'border-primary bg-primary-soft' : 'hover:bg-muted/50'}`}
                onClick={() => setF((s) => ({ ...s, kind: k, item_type: s.item_type === defaultTypeFor(s.kind) ? defaultTypeFor(k) : s.item_type }))}>
                <span className="block font-medium">{label}</span>
                <span className="text-xs text-muted-foreground">{hint}</span>
              </button>
            ))}
          </div>
        </div>
        <Field label="Item name (required)" htmlFor="im-name" error={show('item_name')} className="sm:col-span-2">
          <Input id="im-name" ref={nameRef} value={f.item_name} onChange={field('item_name')} onBlur={blur('item_name')} autoFocus
            placeholder="Cement - OPC 53 grade" aria-invalid={!!show('item_name') || undefined} />
        </Field>
        {nameRepeats.length > 0 && (
          <div className="rounded-lg border border-warning/40 bg-warning-soft p-3 text-sm sm:col-span-2" role="status">
            <p className="flex items-center gap-2 font-medium text-warning"><TriangleAlert className="size-4" /> Did you mean one of these?</p>
            <ul className="mt-2 grid gap-1">
              {nameRepeats.map((s) => (
                <li key={s.id} className="flex flex-wrap items-center justify-between gap-2">
                  <span><span className="font-mono text-xs">{s.item_code}</span> {s.item_name} <span className="text-muted-foreground">({s.units_of_measure}{s.is_active ? '' : ', inactive'}) · {s.reason}</span></span>
                  {onOpenItem && <Button type="button" size="sm" variant="outline" onClick={() => onOpenItem(s.id)}>Open it</Button>}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">If it is a different item, carry on and save.</p>
          </div>
        )}
        <Field label="Item code" htmlFor="im-code" error={show('item_code') ?? (codeOwner ? `This code is already used by '${codeOwner.item_name}'. Use a different code, or open that item.` : undefined)}
          hint={editing ? undefined : 'Suggested for you. Type your own if you have a scheme: letters, numbers and - _ / . up to 30.'}>
          <Input id="im-code" className="font-mono uppercase" value={f.item_code} onChange={field('item_code')} onFocus={(e) => e.target.select()} onBlur={blur('item_code')} disabled={editing}
            maxLength={30} aria-invalid={!!(show('item_code') || codeOwner) || undefined} />
        </Field>
        <Field label="Unit (required)" htmlFor="im-uom" error={show('units_of_measure')} hint="How it is counted or measured: Bags, cum (cubic metre), sqm (square metre), Kgs, Nos (numbers).">
          <Input id="im-uom" list="im-units" value={f.units_of_measure} onChange={field('units_of_measure')} onBlur={() => { blur('units_of_measure')(); const m = matchUnit(f.units_of_measure, units); if (m) set('units_of_measure', m) }}
            placeholder="Start typing: Bags, cum, Kgs" autoComplete="off" aria-invalid={!!show('units_of_measure') || undefined} />
          <datalist id="im-units">{units.map((u) => <option key={u} value={u} />)}</datalist>
        </Field>
        <Field label="Category" htmlFor="im-cat" hint="Groups the item in lists and reports.">
          <Select id="im-cat" value={f.item_category} placeholder="No category" onChange={(e) => setF((s) => ({ ...s, item_category: e.target.value, item_subcategory: '' }))}
            options={(cats.data ?? []).filter((c) => c.is_active || c.name === f.item_category).map((c) => ({ value: c.name, label: c.name }))} />
        </Field>
        <Field label="Subcategory" htmlFor="im-sub" error={show('item_subcategory')}>
          <Select id="im-sub" value={f.item_subcategory} disabled={!subs.length} placeholder={subs.length ? 'No subcategory' : 'None set up for this category'} onChange={field('item_subcategory')}
            options={subs.map((s) => ({ value: s.name, label: s.name }))} />
        </Field>
        <Field label="Grade or specification" htmlFor="im-spec">
          <Input id="im-spec" value={f.specification} onChange={field('specification')} placeholder="OPC 53 grade, 50 kg bag · M25 · Fe550D" />
        </Field>
        <Field label="Make" htmlFor="im-make" hint={f.kind === 'RM' ? 'The brand: UltraTech, Tata Tiscon, Finolex.' : 'Optional for a work item.'}>
          <Input id="im-make" value={f.make} onChange={field('make')} placeholder="UltraTech" />
        </Field>
      </Section>

      <Section title="Pricing and tax">
        <Field label="Usual purchase rate" htmlFor="im-prate" error={show('purchase_rate')} hint="What you normally pay. Optional.">
          <MoneyInput id="im-prate" value={f.purchase_rate} onChange={(v) => set('purchase_rate', v)} invalid={!!show('purchase_rate')} placeholder="415" />
        </Field>
        <Field label="Usual selling rate" htmlFor="im-srate" error={show('selling_rate')} hint="A starting point only. Each site has its own rate under Site Item Pricing.">
          <MoneyInput id="im-srate" value={f.selling_rate} onChange={(v) => set('selling_rate', v)} invalid={!!show('selling_rate')} placeholder="520" />
        </Field>
        <Field label="GST (tax) rate" htmlFor="im-gst" error={show('gst_percent')} hint="The tax charged on this item.">
          <Select id="im-gst" value={f.gst_percent} placeholder="Not set" onChange={field('gst_percent')} options={GST_RATES.map((r) => ({ value: r, label: `${r}%` }))} />
        </Field>
      </Section>

      <div>
        <button type="button" className="flex items-center gap-1 text-sm font-medium text-primary" aria-expanded={more} onClick={() => setMore((m) => !m)}>
          {more ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />} More details (HSN, supplier, stock level, segment, notes)
        </button>
      </div>
      {more && (
        <>
          <Section title="Purchasing and stock">
            <Field label="Usual supplier" htmlFor="im-sup"><Input id="im-sup" value={f.preferred_supplier} onChange={field('preferred_supplier')} /></Field>
            <Field label="Tell me when stock falls below" htmlFor="im-min" error={show('reorder_level')} hint="The store is warned when it holds less than this.">
              <Input id="im-min" type="number" min={0} step="any" value={f.reorder_level} onChange={field('reorder_level')} onBlur={blur('reorder_level')} aria-invalid={!!show('reorder_level') || undefined} />
            </Field>
            <Field label="HSN / SAC code" htmlFor="im-hsn" hint="The government's tax code for the item: HSN for goods, SAC for services. Optional.">
              <Input id="im-hsn" className="font-mono" value={f.hsn_code} onChange={field('hsn_code')} />
            </Field>
            <Field label="Item type" htmlFor="im-type">
              <Select id="im-type" value={f.item_type} onChange={field('item_type')} options={(vocab?.boq_item_types ?? [f.item_type]).map((v) => ({ value: v, label: v }))} />
            </Field>
            <Field label="Segment" htmlFor="im-seg" hint="The company or division it belongs to, if you keep items apart that way.">
              <Input id="im-seg" value={f.segment} onChange={field('segment')} placeholder="YPPL" />
            </Field>
          </Section>
          <Section title="Notes">
            <Field label="Description" htmlFor="im-desc" className="sm:col-span-2" hint="If left blank, the name is used.">
              <Textarea id="im-desc" value={f.description} onChange={field('description')} />
            </Field>
            <Field label="Remarks" htmlFor="im-rem" className="sm:col-span-2"><Textarea id="im-rem" value={f.remarks} onChange={field('remarks')} /></Field>
          </Section>
        </>
      )}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={(e) => set('is_active', e.target.checked)} /> Active (can be put on new BOQ lines and orders)</label>

      <div className="sticky -bottom-5 z-10 -mx-6 -mb-5 flex flex-wrap justify-end gap-2 border-t border-border bg-popover px-6 py-3.5">
        <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        {!editing && <Button type="button" variant="outline" loading={save.isPending && save.variables === true} disabled={save.isPending} onClick={() => submit(true)}>Save and add another</Button>}
        <Button type="submit" loading={save.isPending && save.variables !== true} disabled={save.isPending}>{editing ? 'Save changes' : 'Save item'}</Button>
      </div>
    </form>
  )
}
