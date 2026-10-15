import { useState } from 'react'
import { ArrowDown, ArrowUp, Copy, Download, Eye, FileUp, ListTree, Pencil, Plus, Power, Search } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Card, ConfirmDialog, Input, Select, Skeleton } from '@/components/ui'
import { exportUrl, masterKeys, setItemActive, useCategories, useMasterItems, type ItemFilters, type MasterItem } from '@/api/itemMaster'
import { itemKeys, useItemVocabulary } from '@/api/items'
import { useSites } from '@/api/siteRates'
import { useAction } from '@/lib/mutate'
import { useDebounced } from '@/lib/hooks'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'
import { AddItemsModal } from './AddItemsModal'
import { CategoriesModal } from './CategoriesModal'
import { ImportItemsModal } from './ImportItemsModal'
import { ItemFormModal, type FormMode } from './ItemFormModal'

const COLUMNS: { id: string; label: string; sort?: string; right?: boolean; hide?: string }[] = [
  { id: 'code', label: 'Item code', sort: 'code' },
  { id: 'name', label: 'Item name', sort: 'name' },
  { id: 'desc', label: 'Description', hide: 'max-xl:hidden' },
  { id: 'cat', label: 'Category', sort: 'category', hide: 'max-md:hidden' },
  { id: 'sub', label: 'Subcategory', sort: 'subcategory', hide: 'max-lg:hidden' },
  { id: 'type', label: 'Type', sort: 'type', hide: 'max-lg:hidden' },
  { id: 'uom', label: 'UOM', sort: 'uom' },
  { id: 'rate', label: 'Default rate', sort: 'rate', right: true, hide: 'max-md:hidden' },
  { id: 'sites', label: 'Sites', right: true, hide: 'max-sm:hidden' },
  { id: 'status', label: 'Status', sort: 'status' },
]

/** The BOQ item master: every item once, filed by category, with the sites that use it. */
export default function ItemMasterPage() {
  const { can } = useSession()
  const manage = can('items.manage')
  const vocab = useItemVocabulary()
  const cats = useCategories()
  const sites = useSites()
  const [f, setF] = useState<ItemFilters>({ q: '', category: '', subcategory: '', item_type: '', uom: '', status: 'all', site_id: '', sort: 'code', direction: 'asc', page: 1, page_size: 25 })
  const query = { ...f, q: useDebounced(f.q) }
  const list = useMasterItems(query)
  const [form, setForm] = useState<{ item: MasterItem | null; mode: FormMode | null }>({ item: null, mode: null })
  const [adding, setAdding] = useState(false)
  const [importing, setImporting] = useState(false)
  const [managing, setManaging] = useState(false)
  const [toggling, setToggling] = useState<MasterItem | null>(null)

  const change = (patch: Partial<ItemFilters>) => setF((s) => ({ ...s, page: 1, ...patch }))
  const toggle = useAction((i: MasterItem) => setItemActive(i.id, !i.is_active), { invalidate: [masterKeys.all, itemKeys.all], onSuccess: () => setToggling(null), onError: () => setToggling(null) })
  const subs = cats.data?.find((c) => c.name === f.category)?.subcategories ?? []
  const total = list.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / f.page_size))

  return (
    <>
      <PageHeader
        eyebrow="Store"
        title="Item Master"
        description="Every material and BOQ work item once, with one code that follows it through BOQs, orders, measurements and bills. Rates are set per site, not here."
        actions={
          <>
            <Button variant="outline" asChild>
              <a href={exportUrl({ ...query })}>
                <Download /> Export
              </a>
            </Button>
            {manage && (
              <>
                <Button variant="outline" onClick={() => setManaging(true)}>
                  <ListTree /> Categories
                </Button>
                <Button variant="outline" onClick={() => setImporting(true)}>
                  <FileUp /> Import from Excel
                </Button>
                <Button variant="outline" onClick={() => setAdding(true)}>
                  <Plus /> Add several
                </Button>
                <Button onClick={() => setForm({ item: null, mode: 'create' })}>
                  <Plus /> New item
                </Button>
              </>
            )}
          </>
        }
      />

      <Card className="mb-4 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
        <Input className="lg:col-span-2" type="search" aria-label="Search items" placeholder="Search code, name, description, grade" value={f.q} onChange={(e) => change({ q: e.target.value })} leading={<Search />} />
        <Select aria-label="Category" value={f.category} placeholder="All categories" onChange={(e) => change({ category: e.target.value, subcategory: '' })} options={(cats.data ?? []).map((c) => ({ value: c.name, label: c.name }))} />
        <Select aria-label="Subcategory" value={f.subcategory} placeholder="All subcategories" disabled={!subs.length} onChange={(e) => change({ subcategory: e.target.value })} options={subs.map((s) => ({ value: s.name, label: s.name }))} />
        <Select aria-label="Item type" value={f.item_type} placeholder="All types" onChange={(e) => change({ item_type: e.target.value })} options={(vocab.data?.boq_item_types ?? []).map((v) => ({ value: v, label: v }))} />
        <Select aria-label="Unit" value={f.uom} placeholder="All units" onChange={(e) => change({ uom: e.target.value })} options={(vocab.data?.units ?? []).map((v) => ({ value: v, label: v }))} />
        <Select aria-label="Status" value={f.status} onChange={(e) => change({ status: e.target.value })} options={[{ value: 'all', label: 'Active and inactive' }, { value: 'active', label: 'Active' }, { value: 'inactive', label: 'Inactive' }]} />
        <Select aria-label="Site" value={f.site_id} placeholder="Any site" onChange={(e) => change({ site_id: e.target.value })} options={(sites.data ?? []).map((s) => ({ value: s.id, label: `${s.site_code} ${s.site_name}`.trim() }))} />
      </Card>

      {list.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : list.isError ? (
        <p className="text-sm text-danger">The items could not be loaded. Check your connection and try again.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm" aria-label="Items">
            <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.id} className={`px-3 py-2 ${c.right ? 'text-right' : ''} ${c.hide ?? ''}`} aria-sort={f.sort === c.sort ? (f.direction === 'asc' ? 'ascending' : 'descending') : undefined}>
                    {c.sort ? (
                      <button type="button" className="inline-flex items-center gap-1 uppercase" onClick={() => change({ sort: c.sort!, direction: f.sort === c.sort && f.direction === 'asc' ? 'desc' : 'asc' })}>
                        {c.label}
                        {f.sort === c.sort && (f.direction === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                      </button>
                    ) : (
                      c.label
                    )}
                  </th>
                ))}
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {list.data!.items.map((r) => (
                <tr key={r.id} className={r.is_active ? '' : 'text-muted-foreground'}>
                  <td className="px-3 py-2 font-mono text-[13px]">{r.item_code}</td>
                  <td className="max-w-xs px-3 py-2"><div className="truncate font-medium">{r.item_name}</div>{r.specification && <div className="truncate text-xs text-muted-foreground">{r.specification}</div>}</td>
                  <td className="max-w-xs truncate px-3 py-2 max-xl:hidden">{r.description !== r.item_name ? r.description : ''}</td>
                  <td className="px-3 py-2 max-md:hidden">{r.item_category || '-'}</td>
                  <td className="px-3 py-2 max-lg:hidden">{r.item_subcategory || '-'}</td>
                  <td className="px-3 py-2 max-lg:hidden">{r.item_type}</td>
                  <td className="px-3 py-2">{r.units_of_measure}</td>
                  <td className="px-3 py-2 text-right tabular-nums max-md:hidden">{r.default_rate ? formatINR(r.default_rate) : '-'}</td>
                  <td className="px-3 py-2 text-right tabular-nums max-sm:hidden">{r.sites}</td>
                  <td className="px-3 py-2"><Badge tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? 'Active' : 'Inactive'}</Badge></td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-1">
                      <Button size="icon-sm" variant="ghost" aria-label={`View ${r.item_code}`} onClick={() => setForm({ item: r, mode: 'view' })}><Eye /></Button>
                      {manage && (
                        <>
                          <Button size="icon-sm" variant="ghost" aria-label={`Edit ${r.item_code}`} onClick={() => setForm({ item: r, mode: 'edit' })}><Pencil /></Button>
                          <Button size="icon-sm" variant="ghost" aria-label={`Duplicate ${r.item_code}`} onClick={() => setForm({ item: r, mode: 'duplicate' })}><Copy /></Button>
                          <Button size="icon-sm" variant="ghost" aria-label={`${r.is_active ? 'Deactivate' : 'Activate'} ${r.item_code}`} onClick={() => setToggling(r)}><Power /></Button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {list.data!.items.length === 0 && (
                <tr><td colSpan={COLUMNS.length + 1} className="px-3 py-10 text-center text-muted-foreground">{f.q || f.category || f.site_id ? 'Nothing matches those filters.' : 'No items yet. Add one, or bring them in from Excel.'}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
        <span>{total} item{total === 1 ? '' : 's'}</span>
        <div className="flex items-center gap-2">
          <Select aria-label="Rows per page" value={f.page_size} onChange={(e) => change({ page_size: Number(e.target.value) })} options={[10, 25, 50, 100].map((n) => ({ value: n, label: `${n} per page` }))} />
          <Button size="sm" variant="outline" disabled={f.page <= 1} onClick={() => setF((s) => ({ ...s, page: s.page - 1 }))}>Previous</Button>
          <span>Page {f.page} of {pages}</span>
          <Button size="sm" variant="outline" disabled={f.page >= pages} onClick={() => setF((s) => ({ ...s, page: s.page + 1 }))}>Next</Button>
        </div>
      </div>

      <ItemFormModal item={form.item} mode={form.mode} onClose={() => setForm({ item: null, mode: null })} vocab={vocab.data} />
      <AddItemsModal open={adding} onOpenChange={setAdding} vocab={vocab.data} />
      <ImportItemsModal open={importing} onOpenChange={setImporting} vocab={vocab.data} />
      <CategoriesModal open={managing} onOpenChange={setManaging} />
      <ConfirmDialog
        open={!!toggling}
        onOpenChange={(o) => !o && setToggling(null)}
        title={`${toggling?.is_active ? 'Deactivate' : 'Activate'} ${toggling?.item_code ?? ''}?`}
        description={toggling?.is_active ? 'It stays on every BOQ, order, measurement and bill that already uses it, but cannot be put on new lines.' : 'It can be put on new BOQ lines again.'}
        confirmLabel={toggling?.is_active ? 'Deactivate' : 'Activate'}
        tone={toggling?.is_active ? 'danger' : 'primary'}
        loading={toggle.isPending}
        onConfirm={() => {
          if (toggling) toggle.mutate(toggling)
        }}
      />
    </>
  )
}
