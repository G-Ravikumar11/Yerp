import { useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Copy, Download, Eye, FileUp, ListTree, Pencil, Plus, Power, Search, SlidersHorizontal, X } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Card, ConfirmDialog, Field, Input, Modal, Select, Skeleton } from '@/components/ui'
import { bulkCategory, bulkStatus, exportUrl, fetchItem, masterKeys, setItemActive, useCategories, useMasterItems, type ItemFilters, type MasterItem } from '@/api/itemMaster'
import { itemKeys, useItemVocabulary } from '@/api/items'
import { useSites } from '@/api/siteRates'
import { useAction } from '@/lib/mutate'
import { useDebounced } from '@/lib/hooks'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'
import { AddItemsModal } from './AddItemsModal'
import { CategoriesModal } from './CategoriesModal'
import { ImportItemsModal } from './ImportItemsModal'
import { ItemFormModal, type FormMode } from './ItemFormModal'
import { buildChips, clearAll, clearFilter, isFiltered, loadFilters, saveFilters, stockLabel } from './itemLogic'

const COLUMNS: { id: string; label: string; sort?: string; right?: boolean }[] = [
  { id: 'code', label: 'Code', sort: 'code' },
  { id: 'name', label: 'Item', sort: 'name' },
  { id: 'cat', label: 'Category', sort: 'category' },
  { id: 'uom', label: 'Unit', sort: 'uom' },
  { id: 'rate', label: 'Purchase rate', sort: 'rate', right: true },
  { id: 'stock', label: 'In stock', right: true },
  { id: 'status', label: 'Status', sort: 'status' },
]

/** The item master: every material and BOQ work item once, with the codes that follow it through orders, BOQs and bills. */
export default function ItemMasterPage() {
  const { can, user } = useSession()
  const manage = can('items.manage')
  const who = user?.email ?? ''
  const vocab = useItemVocabulary()
  const cats = useCategories()
  const sites = useSites()
  const [f, setF] = useState<ItemFilters>(() => loadFilters(who))
  useEffect(() => saveFilters(who, f), [who, f])
  const query = { ...f, q: useDebounced(f.q) }
  const list = useMasterItems(query)
  const [showFilters, setShowFilters] = useState(false)
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [form, setForm] = useState<{ item: MasterItem | null; mode: FormMode | null }>({ item: null, mode: null })
  const [adding, setAdding] = useState(false)
  const [importing, setImporting] = useState(false)
  const [managing, setManaging] = useState(false)
  const [toggling, setToggling] = useState<MasterItem | null>(null)
  const [bulkOff, setBulkOff] = useState(false)
  const [moving, setMoving] = useState(false)

  // What was ticked belongs to the list that was on screen: a different page or filter is a different list.
  const change = (patch: Partial<ItemFilters>) => {
    setPicked(new Set())
    setF((s) => ({ ...s, page: 1, ...patch }))
  }
  const go = (page: number) => {
    setPicked(new Set())
    setF((s) => ({ ...s, page }))
  }
  const siteName = (id: string) => sites.data?.find((s) => String(s.id) === id)?.site_name ?? id
  const chips = buildChips(f, siteName)
  const filtered = isFiltered(f)

  const rows = list.data?.items ?? []
  const total = list.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / f.page_size))
  const subs = cats.data?.find((c) => c.name === f.category)?.subcategories ?? []
  const allPicked = rows.length > 0 && rows.every((r) => picked.has(r.id))
  const ids = useMemo(() => [...picked], [picked])
  const flip = (id: number) =>
    setPicked((s) => {
      const next = new Set(s)
      if (!next.delete(id)) next.add(id)
      return next
    })

  const toggle = useAction((i: MasterItem) => setItemActive(i.id, !i.is_active), { invalidate: [masterKeys.all, itemKeys.all], onSuccess: () => setToggling(null), onError: () => setToggling(null) })
  const bulkToggle = useAction((on: boolean) => bulkStatus(ids, on), {
    invalidate: [masterKeys.all, itemKeys.all],
    onSuccess: () => {
      setPicked(new Set())
      setBulkOff(false)
    },
    onError: () => setBulkOff(false),
  })

  const actions = (r: MasterItem) => (
    <div className="flex justify-end gap-1">
      <Button size="icon-sm" variant="ghost" aria-label={`View ${r.item_name}`} onClick={() => setForm({ item: r, mode: 'view' })}><Eye /></Button>
      {manage && (
        <>
          <Button size="icon-sm" variant="ghost" aria-label={`Edit ${r.item_name}`} onClick={() => setForm({ item: r, mode: 'edit' })}><Pencil /></Button>
          <Button size="icon-sm" variant="ghost" aria-label={`Copy ${r.item_name} as a new item`} onClick={() => setForm({ item: r, mode: 'duplicate' })}><Copy /></Button>
          <Button size="icon-sm" variant="ghost" aria-label={`${r.is_active ? 'Deactivate' : 'Activate'} ${r.item_name}`} onClick={() => setToggling(r)}><Power /></Button>
        </>
      )}
    </div>
  )

  return (
    <>
      <PageHeader
        eyebrow="Store"
        title="Item Master"
        description="Every material and BOQ work item, listed once. Each has one code that follows it through BOQs, orders, measurements and bills. Rates for a site are set under Site Item Pricing."
        actions={
          <>
            <Button variant="outline" asChild>
              <a href={exportUrl(query)}><Download /> Export to Excel</a>
            </Button>
            {manage && (
              <>
                <Button variant="outline" onClick={() => setManaging(true)}><ListTree /> Categories</Button>
                <Button variant="outline" onClick={() => setImporting(true)}><FileUp /> Import from Excel</Button>
                <Button variant="outline" onClick={() => setAdding(true)}><Plus /> Add several</Button>
                <Button onClick={() => setForm({ item: null, mode: 'create' })}><Plus /> New item</Button>
              </>
            )}
          </>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="min-w-[14rem] flex-1 sm:max-w-md">
          <Input type="search" aria-label="Search items" placeholder="Search by code, name or grade" value={f.q} onChange={(e) => change({ q: e.target.value })} leading={<Search />} />
        </div>
        <Button variant="outline" aria-expanded={showFilters} onClick={() => setShowFilters((v) => !v)}>
          <SlidersHorizontal /> Filters{chips.length > 0 && <Badge tone="ember" className="ml-1">{chips.length}</Badge>}
        </Button>
      </div>

      {showFilters && (
        <Card className="mb-3 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Category" htmlFor="f-cat">
            <Select id="f-cat" value={f.category} placeholder="Any category" onChange={(e) => change({ category: e.target.value, subcategory: '' })} options={(cats.data ?? []).map((c) => ({ value: c.name, label: c.name }))} />
          </Field>
          <Field label="Subcategory" htmlFor="f-sub">
            <Select id="f-sub" value={f.subcategory} placeholder={subs.length ? 'Any subcategory' : 'Choose a category first'} disabled={!subs.length} onChange={(e) => change({ subcategory: e.target.value })} options={subs.map((s) => ({ value: s.name, label: s.name }))} />
          </Field>
          <Field label="Type" htmlFor="f-type">
            <Select id="f-type" value={f.item_type} placeholder="Any type" onChange={(e) => change({ item_type: e.target.value })} options={(vocab.data?.boq_item_types ?? []).map((v) => ({ value: v, label: v }))} />
          </Field>
          <Field label="Unit" htmlFor="f-uom" hint="How the item is counted: bags, cum, kg, nos.">
            <Select id="f-uom" value={f.uom} placeholder="Any unit" onChange={(e) => change({ uom: e.target.value })} options={(vocab.data?.units ?? []).map((v) => ({ value: v, label: v }))} />
          </Field>
          <Field label="Show" htmlFor="f-status">
            <Select id="f-status" value={f.status} onChange={(e) => change({ status: e.target.value })} options={[{ value: 'active', label: 'Active items' }, { value: 'inactive', label: 'Inactive items' }, { value: 'all', label: 'Active and inactive' }]} />
          </Field>
          {(sites.data?.length ?? 0) > 0 && (
            <Field label="Used at site" htmlFor="f-site">
              <Select id="f-site" value={f.site_id} placeholder="Any site" onChange={(e) => change({ site_id: e.target.value })} options={(sites.data ?? []).map((s) => ({ value: s.id, label: `${s.site_code} ${s.site_name}`.trim() }))} />
            </Field>
          )}
        </Card>
      )}

      {(chips.length > 0 || f.q) && (
        <div className="mb-3 flex flex-wrap items-center gap-2" aria-label="Filters in use">
          {chips.map((c) => (
            <button key={c.key} type="button" className="inline-flex items-center gap-1 rounded-full bg-muted px-3 py-1 text-xs ring-1 ring-border hover:bg-muted/70" aria-label={`Remove filter ${c.label}`} onClick={() => { setPicked(new Set()); setF((s) => clearFilter(s, c.key)) }}>
              {c.label} <X className="size-3" />
            </button>
          ))}
          <Button size="sm" variant="ghost" onClick={() => { setPicked(new Set()); setF((s) => clearAll(s)) }}>Clear all</Button>
        </div>
      )}

      {picked.size > 0 && (
        <div role="region" aria-label="Selected items" className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border bg-primary-soft px-3 py-2 text-sm">
          <strong>{picked.size} selected</strong>
          {manage && (
            <>
              <Button size="sm" variant="outline" loading={bulkToggle.isPending && bulkToggle.variables === true} onClick={() => bulkToggle.mutate(true)}>Activate</Button>
              <Button size="sm" variant="outline" onClick={() => setBulkOff(true)}>Deactivate</Button>
              <Button size="sm" variant="outline" onClick={() => setMoving(true)}>Change category</Button>
            </>
          )}
          <Button size="sm" variant="outline" asChild><a href={exportUrl(query, ids)}><Download /> Export selected</a></Button>
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setPicked(new Set())}>Clear selection</Button>
        </div>
      )}

      {list.isPending ? (
        <div className="grid gap-2" aria-busy="true" aria-label="Loading items">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
      ) : list.isError ? (
        <div className="rounded-lg border border-danger/30 p-6 text-center">
          <p className="font-medium text-danger">The items could not be loaded.</p>
          <p className="mt-1 text-sm text-muted-foreground">Check your connection, then try again.</p>
          <Button className="mt-3" variant="outline" onClick={() => list.refetch()}>Try again</Button>
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center">
          {filtered ? (
            <>
              <p className="font-medium">No items match these filters.</p>
              <p className="mt-1 text-sm text-muted-foreground">Try a different search, or take the filters off.</p>
              <Button className="mt-4" variant="outline" onClick={() => { setPicked(new Set()); setF((s) => clearAll({ ...s, q: '' })) }}>Clear search and filters</Button>
            </>
          ) : (
            <>
              <p className="font-medium">No items yet.</p>
              <p className="mt-1 text-sm text-muted-foreground">{manage ? 'Add your first item, or bring your list in from Excel.' : 'Items appear here once the store adds them.'}</p>
              {manage && (
                <div className="mt-4 flex justify-center gap-2">
                  <Button onClick={() => setForm({ item: null, mode: 'create' })}><Plus /> Add your first item</Button>
                  <Button variant="outline" onClick={() => setImporting(true)}><FileUp /> Import from Excel</Button>
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        <>
          <div className="hidden overflow-x-auto rounded-lg border md:block">
            <table className="w-full text-sm" aria-label="Items">
              <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  {manage && (
                    <th className="w-10 px-3 py-2">
                      <input type="checkbox" aria-label="Select all items on this page" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(rows.map((r) => r.id)))} />
                    </th>
                  )}
                  {COLUMNS.map((c) => (
                    <th key={c.id} className={`px-3 py-2 ${c.right ? 'text-right' : ''}`} aria-sort={f.sort === c.sort ? (f.direction === 'asc' ? 'ascending' : 'descending') : undefined}>
                      {c.sort ? (
                        <button type="button" className="inline-flex items-center gap-1 uppercase" onClick={() => change({ sort: c.sort!, direction: f.sort === c.sort && f.direction === 'asc' ? 'desc' : 'asc' })}>
                          {c.label}{f.sort === c.sort && (f.direction === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                        </button>
                      ) : c.label}
                    </th>
                  ))}
                  <th className="px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((r) => (
                  <tr key={r.id} className={r.is_active ? '' : 'bg-muted/20 text-muted-foreground'}>
                    {manage && <td className="px-3 py-2"><input type="checkbox" aria-label={`Select ${r.item_name}`} checked={picked.has(r.id)} onChange={() => flip(r.id)} /></td>}
                    <td className="px-3 py-2 font-mono text-[13px]">{r.item_code}</td>
                    <td className="max-w-sm px-3 py-2">
                      <button type="button" className="block max-w-full truncate text-left font-medium hover:underline" onClick={() => setForm({ item: r, mode: 'view' })}>{r.item_name}</button>
                      {r.specification && <div className="truncate text-xs text-muted-foreground">{r.specification}</div>}
                    </td>
                    <td className="px-3 py-2">{r.item_category || '-'}</td>
                    <td className="px-3 py-2">{r.units_of_measure}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{r.purchase_rate ? formatINR(r.purchase_rate) : '-'}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{stockLabel(r.kind, r.stock, r.units_of_measure)}</td>
                    <td className="px-3 py-2"><Badge tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? 'Active' : 'Inactive'}</Badge></td>
                    <td className="px-3 py-2">{actions(r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ul className="grid gap-3 md:hidden" aria-label="Items">
            {rows.map((r) => (
              <li key={r.id} className={`rounded-lg border p-3 ${r.is_active ? '' : 'bg-muted/20 text-muted-foreground'}`}>
                <div className="flex items-start gap-3">
                  {manage && <input className="mt-1" type="checkbox" aria-label={`Select ${r.item_name}`} checked={picked.has(r.id)} onChange={() => flip(r.id)} />}
                  <div className="min-w-0 flex-1">
                    <button type="button" className="block text-left font-medium" onClick={() => setForm({ item: r, mode: 'view' })}>{r.item_name}</button>
                    <div className="font-mono text-xs text-muted-foreground">{r.item_code}{r.specification ? ` · ${r.specification}` : ''}</div>
                  </div>
                  <Badge tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? 'Active' : 'Inactive'}</Badge>
                </div>
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                  <div><dt className="text-xs text-muted-foreground">Category</dt><dd>{r.item_category || '-'}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Unit</dt><dd>{r.units_of_measure}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Purchase rate</dt><dd>{r.purchase_rate ? formatINR(r.purchase_rate) : '-'}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">In stock</dt><dd>{stockLabel(r.kind, r.stock, r.units_of_measure)}</dd></div>
                </dl>
                <div className="mt-2">{actions(r)}</div>
              </li>
            ))}
          </ul>
        </>
      )}

      {rows.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
          <span>{total} item{total === 1 ? '' : 's'}</span>
          <div className="flex items-center gap-2">
            <Select aria-label="Items per page" value={f.page_size} onChange={(e) => change({ page_size: Number(e.target.value) })} options={[10, 25, 50, 100].map((n) => ({ value: n, label: `${n} per page` }))} />
            <Button size="sm" variant="outline" disabled={f.page <= 1} onClick={() => go(f.page - 1)}>Previous</Button>
            <span>Page {f.page} of {pages}</span>
            <Button size="sm" variant="outline" disabled={f.page >= pages} onClick={() => go(f.page + 1)}>Next</Button>
          </div>
        </div>
      )}

      <ItemFormModal item={form.item} mode={form.mode} onClose={() => setForm({ item: null, mode: null })} vocab={vocab.data}
        onOpenItem={(id) => { fetchItem(id).then((item) => setForm({ item, mode: 'view' })).catch(() => toast.error('That item could not be opened.')) }} />
      <AddItemsModal open={adding} onOpenChange={setAdding} vocab={vocab.data} />
      <ImportItemsModal open={importing} onOpenChange={setImporting} vocab={vocab.data} />
      <CategoriesModal open={managing} onOpenChange={setManaging} />
      <MoveCategory open={moving} onOpenChange={setMoving} ids={ids} onDone={() => setPicked(new Set())} />
      <ConfirmDialog
        open={!!toggling}
        onOpenChange={(o) => !o && setToggling(null)}
        title={`${toggling?.is_active ? 'Deactivate' : 'Activate'} ${toggling?.item_name ?? ''}?`}
        description={toggling?.is_active ? 'It stays on every BOQ, order, measurement and bill that already uses it, but cannot be put on new lines.' : 'It can be put on new BOQ lines again.'}
        confirmLabel={toggling?.is_active ? 'Deactivate' : 'Activate'}
        tone={toggling?.is_active ? 'danger' : 'primary'}
        loading={toggle.isPending}
        onConfirm={() => { if (toggling) toggle.mutate(toggling) }}
      />
      <ConfirmDialog
        open={bulkOff}
        onOpenChange={setBulkOff}
        title={`Deactivate ${picked.size} item${picked.size === 1 ? '' : 's'}?`}
        description="They stay on every BOQ, order, measurement and bill that already uses them, but cannot be put on new lines."
        confirmLabel="Deactivate"
        tone="danger"
        loading={bulkToggle.isPending}
        onConfirm={() => bulkToggle.mutate(false)}
      />
    </>
  )
}

/** Move the ticked items to another category in one go. */
function MoveCategory({ open, onOpenChange, ids, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; ids: number[]; onDone: () => void }) {
  const cats = useCategories()
  const [cat, setCat] = useState('')
  const [sub, setSub] = useState('')
  const subs = cats.data?.find((c) => c.name === cat)?.subcategories ?? []
  const move = useAction(() => bulkCategory(ids, cat, sub), { invalidate: [masterKeys.all, itemKeys.all], onSuccess: () => { onDone(); onOpenChange(false) } })
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={`Change category of ${ids.length} item${ids.length === 1 ? '' : 's'}`} size="sm"
      footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={move.isPending} onClick={() => move.mutate()}>Move</Button></>}>
      <div className="grid gap-3">
        <Field label="New category" htmlFor="mv-cat"><Select id="mv-cat" value={cat} placeholder="No category" onChange={(e) => { setCat(e.target.value); setSub('') }} options={(cats.data ?? []).map((c) => ({ value: c.name, label: c.name }))} /></Field>
        <Field label="New subcategory" htmlFor="mv-sub"><Select id="mv-sub" value={sub} disabled={!subs.length} placeholder={subs.length ? 'No subcategory' : 'None set up'} onChange={(e) => setSub(e.target.value)} options={subs.map((s) => ({ value: s.name, label: s.name }))} /></Field>
      </div>
    </Modal>
  )
}
