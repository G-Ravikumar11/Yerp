import { useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Download, FileUp, ListTree, Pencil, Plus, Power, Search, SlidersHorizontal, X } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Card, ConfirmDialog, Field, Input, Select, Skeleton, Tabs } from '@/components/ui'
import { bulkStatus, exportUrl, fetchItem, masterKeys, setItemActive, useCategories, useItemGaps, useMasterItems, useWhereUsed, type Gap, type ItemFilters, type MasterItem } from '@/api/itemMaster'
import { itemKeys, useItemVocabulary } from '@/api/items'
import { useSites } from '@/api/siteRates'
import { useAction } from '@/lib/mutate'
import { useDebounced } from '@/lib/hooks'
import { ApiError } from '@/lib/api'
import { useSession } from '@/lib/session'
import { cn, formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'
import { BulkEditModal } from './BulkEditModal'
import { CategoriesModal } from './CategoriesModal'
import { ImportItemsModal } from './ImportItemsModal'
import { ItemDetailModal, UsageList } from './ItemDetailModal'
import { ItemFormModal, type FormMode } from './ItemFormModal'
import { GAP_LABEL, NO_CATEGORY, buildChips, gapPhrase, clearAll, clearFilter, isFiltered, loadFilters, purchaseRateOf, saveFilters, stockLabel } from './itemLogic'

// Fixed widths, so a long name is cut with an ellipsis instead of pushing the row off the screen. The name takes the rest.
const COLUMNS: { id: string; label: string; sort?: string; right?: boolean; hide?: string; width?: string }[] = [
  { id: 'code', label: 'Code', sort: 'code', width: 'w-24' },
  { id: 'name', label: 'Item', sort: 'name' },
  { id: 'cat', label: 'Category', sort: 'category', hide: 'max-lg:hidden', width: 'w-36' },
  { id: 'uom', label: 'Unit', sort: 'uom', width: 'w-16' },
  { id: 'gst', label: 'GST', hide: 'max-xl:hidden', width: 'w-14' },
  { id: 'rate', label: 'Purchase rate', sort: 'rate', right: true, width: 'w-32' },
  { id: 'stock', label: 'In stock', right: true, hide: 'max-2xl:hidden', width: 'w-28' },
  { id: 'status', label: 'Status', sort: 'status', width: 'w-[5.5rem]' },
]
const GAPS: Gap[] = ['category', 'gst', 'hsn', 'rate', 'make']

/** A dash for a detail nobody has filled in yet: the gap is plain to see without a sentence in every row. */
const Missing = () => <span className="text-subtle" aria-label="Not filled in">-</span>

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
  const gaps = useItemGaps({ status: f.status === 'inactive' ? 'inactive' : 'active', kind: f.kind })
  const [showFilters, setShowFilters] = useState(false)
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [form, setForm] = useState<{ item: MasterItem | null; mode: FormMode | null }>({ item: null, mode: null })
  const [importing, setImporting] = useState(false)
  const [managing, setManaging] = useState(false)
  const [detail, setDetail] = useState<MasterItem | null>(null)
  const [toggling, setToggling] = useState<MasterItem | null>(null)
  const [bulkNote, setBulkNote] = useState('')
  const [bulkOff, setBulkOff] = useState(false)
  const [editingMany, setEditingMany] = useState(false)

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
  const counts = list.data?.counts
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

  const toggle = useAction((i: MasterItem) => setItemActive(i.id, !i.is_active, true), { invalidate: [masterKeys.all, itemKeys.all], onSuccess: () => { setToggling(null); setDetail(null) }, onError: () => setToggling(null) })
  const usage = useWhereUsed(toggling && toggling.is_active ? toggling.id : null)
  const bulkToggle = useAction((v: { on: boolean; confirm: boolean }) => bulkStatus(ids, v.on, v.confirm), {
    invalidate: [masterKeys.all, itemKeys.all],
    onSuccess: () => {
      setPicked(new Set())
      setBulkOff(false)
      setBulkNote('')
    },
    // Some of them are in use: nothing was changed, and the server says how many. Ask again, knowing that.
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) setBulkNote(err.message)
      else setBulkOff(false)
    },
  })

  const actions = (r: MasterItem) =>
    manage ? (
      <div className="flex justify-end gap-0.5">
        <Button size="icon-sm" variant="ghost" aria-label={`Edit ${r.item_name}`} title="Edit" onClick={() => setForm({ item: r, mode: 'edit' })}><Pencil /></Button>
        <Button size="icon-sm" variant="ghost" aria-label={`${r.is_active ? 'Deactivate' : 'Activate'} ${r.item_name}`} title={r.is_active ? 'Deactivate' : 'Activate'} onClick={() => setToggling(r)}><Power /></Button>
      </div>
    ) : null
  const sub = (r: MasterItem) => [r.specification, r.make].filter(Boolean).join(' · ')
  const anyGap = !!gaps.data && GAPS.some((g) => gaps.data![g] > 0)

  return (
    <>
      <PageHeader
        eyebrow="Store"
        title="Item Master"
        description="Every material and work item, listed once. Each code follows its item through BOQs, orders, measurements and bills. Rates for a site are set under Site Item Pricing."
        actions={
          <>
            <Button variant="outline" asChild>
              <a href={exportUrl(query)}><Download /> Export</a>
            </Button>
            {manage && (
              <>
                <Button variant="outline" onClick={() => setManaging(true)}><ListTree /> Categories</Button>
                <Button variant="outline" onClick={() => setImporting(true)}><FileUp /> Import from Excel</Button>
                <Button onClick={() => setForm({ item: null, mode: 'create' })}><Plus /> New item</Button>
              </>
            )}
          </>
        }
      />

      <div className="mb-4 w-fit max-w-full">
        <Tabs label="Show" value={f.kind || 'all'} onChange={(v) => change({ kind: v === 'all' ? '' : v })} items={[
          { value: 'all', label: 'All items', count: counts ? counts.RM + counts.FG : undefined },
          { value: 'RM', label: 'Materials', count: counts?.RM },
          { value: 'FG', label: 'Work items', count: counts?.FG },
        ]} />
      </div>

      {manage && anyGap && f.status !== 'inactive' && (
        <section aria-label="Details still missing" className="mb-4 rounded-xl border border-border bg-card px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <p className="text-sm font-medium">Details still missing</p>
            <div className="flex flex-wrap gap-1.5">
              {GAPS.filter((g) => gaps.data![g] > 0).map((g) => {
                const on = f.missing === g
                return (
                  <button key={g} type="button" aria-pressed={on} onClick={() => change({ missing: on ? '' : g })}
                    className={cn('inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium ring-1 ring-inset transition-colors',
                      on ? 'bg-primary text-primary-foreground ring-primary' : 'bg-warning-soft text-warning ring-warning/30 hover:bg-warning/20')}>
                    {GAP_LABEL[g]} <span className="tabular opacity-80">{new Intl.NumberFormat('en-IN').format(gaps.data![g])}</span>
                  </button>
                )
              })}
            </div>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">
            {f.missing ? `Showing the items with ${gapPhrase(f.missing)}. Tick them (or every one on the page) and press Edit selected to fill it in for all of them at once.` : 'Pick one to list those items, then tick them and fill the detail in for all of them at once.'}
          </p>
        </section>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="min-w-[14rem] flex-1 sm:max-w-md">
          <Input type="search" aria-label="Search items" placeholder="Search by code, name, grade or make" value={f.q} onChange={(e) => change({ q: e.target.value })} leading={<Search />} />
        </div>
        <Button variant="outline" aria-expanded={showFilters} onClick={() => setShowFilters((v) => !v)}>
          <SlidersHorizontal /> Filters{chips.length > 0 && <Badge tone="ember" className="ml-1">{chips.length}</Badge>}
        </Button>
        <span className="tabular ml-auto text-xs text-muted-foreground">{new Intl.NumberFormat('en-IN').format(total)} {total === 1 ? 'item' : 'items'}</span>
      </div>

      {showFilters && (
        <Card className="mb-3 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Category" htmlFor="f-cat">
            <Select id="f-cat" value={f.category} placeholder="Any category" onChange={(e) => change({ category: e.target.value, subcategory: '' })} options={[{ value: NO_CATEGORY, label: 'No category yet' }, ...(cats.data ?? []).map((c) => ({ value: c.name, label: c.name }))]} />
          </Field>
          <Field label="Subcategory" htmlFor="f-sub">
            <Select id="f-sub" value={f.subcategory} placeholder={subs.length ? 'Any subcategory' : 'Choose a category first'} disabled={!subs.length} onChange={(e) => change({ subcategory: e.target.value })} options={subs.map((s) => ({ value: s.name, label: s.name }))} />
          </Field>
          <Field label="Type" htmlFor="f-type">
            <Select id="f-type" value={f.item_type} placeholder="Any type" onChange={(e) => change({ item_type: e.target.value })} options={(vocab.data?.boq_item_types ?? []).map((v) => ({ value: v, label: v }))} />
          </Field>
          <Field label="Unit" htmlFor="f-uom">
            <Select id="f-uom" value={f.uom} placeholder="Any unit" onChange={(e) => change({ uom: e.target.value })} options={(vocab.data?.units ?? []).map((v) => ({ value: v, label: v }))} />
          </Field>
          <Field label="Show" htmlFor="f-status">
            <Select id="f-status" value={f.status} onChange={(e) => change({ status: e.target.value })} options={[{ value: 'active', label: 'Active items' }, { value: 'inactive', label: 'Inactive items' }, { value: 'all', label: 'Active and inactive' }]} />
          </Field>
          <Field label="Missing" htmlFor="f-missing">
            <Select id="f-missing" value={f.missing} placeholder="Anything" onChange={(e) => change({ missing: e.target.value as Gap | '' })} options={GAPS.map((g) => ({ value: g, label: GAP_LABEL[g] }))} />
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
            <button key={c.key} type="button" className="inline-flex items-center gap-1 rounded-md bg-muted px-3 py-1 text-xs ring-1 ring-border hover:bg-muted/70" aria-label={`Remove filter ${c.label}`} onClick={() => { setPicked(new Set()); setF((s) => clearFilter(s, c.key)) }}>
              {c.label} <X className="size-3" />
            </button>
          ))}
          <Button size="sm" variant="ghost" onClick={() => { setPicked(new Set()); setF((s) => clearAll(s)) }}>Clear all</Button>
        </div>
      )}

      {picked.size > 0 && (
        <div role="region" aria-label="Selected items" className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary-soft px-3 py-2 text-sm">
          <strong>{picked.size} selected</strong>
          {manage && (
            <>
              <Button size="sm" onClick={() => setEditingMany(true)}><Pencil /> Edit selected</Button>
              <Button size="sm" variant="outline" loading={bulkToggle.isPending && bulkToggle.variables?.on === true} onClick={() => bulkToggle.mutate({ on: true, confirm: true })}>Activate</Button>
              <Button size="sm" variant="outline" onClick={() => setBulkOff(true)}>Deactivate</Button>
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
        <div className="rounded-xl border border-dashed p-10 text-center">
          {filtered || f.kind ? (
            <>
              <p className="font-medium">No items match.</p>
              <p className="mt-1 text-sm text-muted-foreground">{f.missing ? `No item here has ${gapPhrase(f.missing)}: nothing left to fill in.` : 'Try a different search, or take the filters off.'}</p>
              <Button className="mt-4" variant="outline" onClick={() => { setPicked(new Set()); setF((s) => ({ ...clearAll({ ...s, q: '' }), kind: '' })) }}>Show every item</Button>
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
          <div className="hidden overflow-hidden rounded-xl border border-border bg-card md:block">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[46rem] table-fixed text-[13.5px]" aria-label="Items">
                <thead className="bg-surface text-left">
                  <tr>
                    {manage && (
                      <th className="w-10 border-b border-border px-4 py-2.5">
                        <input type="checkbox" aria-label="Select all items on this page" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(rows.map((r) => r.id)))} />
                      </th>
                    )}
                    {COLUMNS.map((c) => (
                      <th key={c.id} className={cn('whitespace-nowrap border-b border-border px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground', c.right && 'text-right', c.hide, c.width)} aria-sort={f.sort === c.sort ? (f.direction === 'asc' ? 'ascending' : 'descending') : undefined}>
                        {c.sort ? (
                          <button type="button" className={cn('inline-flex items-center gap-1 uppercase transition-colors hover:text-foreground', f.sort === c.sort && 'text-foreground')} onClick={() => change({ sort: c.sort!, direction: f.sort === c.sort && f.direction === 'asc' ? 'desc' : 'asc' })}>
                            {c.label}{f.sort === c.sort && (f.direction === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                          </button>
                        ) : c.label}
                      </th>
                    ))}
                    {manage && <th className="w-20 border-b border-border px-3 py-2.5"><span className="sr-only">Actions</span></th>}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className={cn('border-b border-border transition-colors last:border-b-0 hover:bg-accent/60', !r.is_active && 'text-muted-foreground', picked.has(r.id) && 'bg-primary-soft/60')}>
                      {manage && <td className="px-4 py-2.5"><input type="checkbox" aria-label={`Select ${r.item_name}`} checked={picked.has(r.id)} onChange={() => flip(r.id)} /></td>}
                      <td className="truncate px-3 py-2.5">
                        <div className="truncate font-mono text-[13px]" title={r.item_code}>{r.item_code}</div>
                        <div className="text-[11px] text-muted-foreground">{r.kind === 'RM' ? 'Material' : 'Work item'}</div>
                      </td>
                      <td className="px-3 py-2.5">
                        <button type="button" className="block max-w-full truncate text-left font-medium hover:text-primary hover:underline" title={r.item_name} onClick={() => setDetail(r)}>{r.item_name}</button>
                        {sub(r) && <div className="truncate text-xs text-muted-foreground" title={sub(r)}>{sub(r)}</div>}
                      </td>
                      <td className="px-3 py-2.5 max-lg:hidden">
                        {r.item_category ? <div className="truncate" title={[r.item_category, r.item_subcategory].filter(Boolean).join(' › ')}>{r.item_category}{r.item_subcategory && <span className="text-muted-foreground"> › {r.item_subcategory}</span>}</div> : <Missing />}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5">{r.units_of_measure}</td>
                      <td className="whitespace-nowrap px-3 py-2.5 tabular max-xl:hidden">{r.item_tax_type || <Missing />}</td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular"><Rate item={r} /></td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular max-2xl:hidden">{r.kind === 'RM' || r.stock !== null ? stockLabel(r.kind, r.stock, r.units_of_measure) : <Missing />}</td>
                      <td className="whitespace-nowrap px-3 py-2.5"><Badge tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? 'Active' : 'Inactive'}</Badge></td>
                      {manage && <td className="px-3 py-2">{actions(r)}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <ul className="grid gap-3 md:hidden" aria-label="Items">
            {rows.map((r) => (
              <li key={r.id} className={cn('rounded-xl border border-border bg-card p-3', !r.is_active && 'text-muted-foreground')}>
                <div className="flex items-start gap-3">
                  {manage && <input className="mt-1" type="checkbox" aria-label={`Select ${r.item_name}`} checked={picked.has(r.id)} onChange={() => flip(r.id)} />}
                  <div className="min-w-0 flex-1">
                    <button type="button" className="block text-left font-medium" onClick={() => setDetail(r)}>{r.item_name}</button>
                    <div className="truncate font-mono text-xs text-muted-foreground">{r.item_code} · {r.kind === 'RM' ? 'Material' : 'Work item'}{sub(r) ? ` · ${sub(r)}` : ''}</div>
                  </div>
                  <Badge tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? 'Active' : 'Inactive'}</Badge>
                </div>
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                  <div><dt className="text-xs text-muted-foreground">Category</dt><dd>{r.item_category || <Missing />}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Unit · GST</dt><dd>{r.units_of_measure} · {r.item_tax_type || <Missing />}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Purchase rate</dt><dd><Rate item={r} /></dd></div>
                  <div><dt className="text-xs text-muted-foreground">In stock</dt><dd>{r.kind === 'RM' || r.stock !== null ? stockLabel(r.kind, r.stock, r.units_of_measure) : <Missing />}</dd></div>
                </dl>
                {manage && <div className="mt-2">{actions(r)}</div>}
              </li>
            ))}
          </ul>
        </>
      )}

      {rows.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
          <span className="tabular">{(f.page - 1) * f.page_size + 1}-{Math.min(total, f.page * f.page_size)} of {new Intl.NumberFormat('en-IN').format(total)}</span>
          <div className="flex items-center gap-2">
            <Select aria-label="Items per page" value={f.page_size} onChange={(e) => change({ page_size: Number(e.target.value) })} options={[10, 25, 50, 100, 200].map((n) => ({ value: n, label: `${n} per page` }))} />
            <Button size="sm" variant="outline" disabled={f.page <= 1} onClick={() => go(f.page - 1)}>Previous</Button>
            <span className="tabular">Page {f.page} of {pages}</span>
            <Button size="sm" variant="outline" disabled={f.page >= pages} onClick={() => go(f.page + 1)}>Next</Button>
          </div>
        </div>
      )}

      <ItemFormModal item={form.item} mode={form.mode} onClose={() => setForm({ item: null, mode: null })} vocab={vocab.data}
        onOpenItem={(id) => { fetchItem(id).then((item) => { setForm({ item: null, mode: null }); setDetail(item) }).catch(() => toast.error('That item could not be opened.')) }} />
      <ItemDetailModal item={detail} manage={manage} onClose={() => setDetail(null)} onEdit={(i) => { setDetail(null); setForm({ item: i, mode: 'edit' }) }}
        onCopy={(i) => { setDetail(null); setForm({ item: i, mode: 'duplicate' }) }} onToggle={(i) => setToggling(i)} />
      <ImportItemsModal open={importing} onOpenChange={setImporting} vocab={vocab.data} />
      <CategoriesModal open={managing} onOpenChange={setManaging} />
      <BulkEditModal open={editingMany} onOpenChange={setEditingMany} ids={ids} focus={f.missing} vocab={vocab.data} onDone={() => setPicked(new Set())} />
      <ConfirmDialog
        open={!!toggling}
        onOpenChange={(o) => !o && setToggling(null)}
        title={`${toggling?.is_active ? 'Deactivate' : 'Activate'} ${toggling?.item_name ?? ''}?`}
        description={toggling?.is_active ? 'It stays on every BOQ, order, measurement and bill that already uses it, but cannot be put on new lines.' : 'It can be put on new BOQ lines again.'}
        confirmLabel={toggling?.is_active ? (usage.data?.total ? 'Deactivate anyway' : 'Deactivate') : 'Activate'}
        tone={toggling?.is_active ? 'danger' : 'primary'}
        loading={toggle.isPending}
        onConfirm={() => { if (toggling) toggle.mutate(toggling) }}
      >
        {toggling?.is_active && (usage.isPending ? <Skeleton className="h-10 w-full" /> : usage.data && usage.data.total > 0 && (
          <div className="mt-3 rounded-md border border-warning/40 bg-warning-soft p-3 text-sm">
            <p className="mb-2 font-medium text-warning">This item is in use in {usage.data.total} place{usage.data.total === 1 ? '' : 's'}:</p>
            <UsageList groups={usage.data.groups} />
          </div>
        ))}
      </ConfirmDialog>
      <ConfirmDialog
        open={bulkOff}
        onOpenChange={(o) => { setBulkOff(o); if (!o) setBulkNote('') }}
        title={`Deactivate ${picked.size} item${picked.size === 1 ? '' : 's'}?`}
        description={bulkNote || 'They stay on every BOQ, order, measurement and bill that already uses them, but cannot be put on new lines.'}
        confirmLabel={bulkNote ? 'Deactivate anyway' : 'Deactivate'}
        tone="danger"
        loading={bulkToggle.isPending}
        onConfirm={() => bulkToggle.mutate({ on: false, confirm: !!bulkNote })}
      />
    </>
  )
}

/** The purchase rate, or the last rate the item was bought or sold at (said so), or a dash. */
function Rate({ item }: { item: MasterItem }) {
  const rate = purchaseRateOf(item)
  if (!rate) return <Missing />
  return (
    <span>
      {formatINR(rate.value)}
      {rate.lastUsed && <span className="block text-[11px] text-muted-foreground">last rate used</span>}
    </span>
  )
}
