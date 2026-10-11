import { useState } from 'react'
import { Download, FileUp, Plus, Search, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Input, Tabs } from '@/components/ui'
import { deleteItem, itemKeys, useItemVocabulary, useItems, type Item } from '@/api/items'
import { useAction } from '@/lib/mutate'
import { useDebounced } from '@/lib/hooks'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'
import { AddItemsModal } from './AddItemsModal'
import { EditItemModal } from './EditItemModal'
import { ImportItemsModal } from './ImportItemsModal'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

type Tab = '' | 'RM' | 'FG'

export default function ItemMasterPage() {
  const { can } = useSession()
  const manage = can('items.manage')
  const [tab, setTab] = useState<Tab>('')
  const [q, setQ] = useState('')
  const search = useDebounced(q)
  const items = useItems(tab, search)
  const vocab = useItemVocabulary()
  const [adding, setAdding] = useState(false)
  const [importing, setImporting] = useState(false)
  const [editing, setEditing] = useState<Item | null>(null)
  const [removing, setRemoving] = useState<Item | null>(null)

  const remove = useAction((item: Item) => deleteItem(item.id), {
    invalidate: [itemKeys.all],
    success: (_r, item) => `${item.item_code} removed.`,
    onSuccess: () => setRemoving(null),
    onError: () => setRemoving(null),
  })

  const counts = items.data?.counts
  const columns: TableColumn<Item>[] = [
    { id: 'code', header: 'Code', width: '7rem', sort: (r) => r.item_code, cell: (r) => <span className="font-mono text-[13px]">{r.item_code}</span> },
    {
      id: 'name',
      header: 'Item',
      sort: (r) => r.item_name,
      cell: (r) => (
        <div className="max-w-md">
          <div className="truncate font-medium">{r.item_name}</div>
          {r.description && r.description !== r.item_name && <div className="truncate text-xs text-muted-foreground">{r.description}</div>}
        </div>
      ),
    },
    { id: 'kind', header: 'Kind', sort: (r) => r.kind, cell: (r) => <Badge tone={r.kind === 'FG' ? 'ember' : 'neutral'}>{r.kind === 'FG' ? 'Finished good' : 'Raw material'}</Badge>, hideBelow: 'md' },
    { id: 'unit', header: 'Unit', sort: (r) => r.units_of_measure, cell: (r) => r.units_of_measure },
    { id: 'hsn', header: 'HSN / SAC', cell: (r) => <span className="font-mono text-xs">{r.hsn_code || '-'}</span>, hideBelow: 'lg' },
    { id: 'tax', header: 'Tax', cell: (r) => r.item_tax_type || '-', hideBelow: 'lg' },
    { id: 'rate', header: 'Last rate', align: 'right', sort: (r) => r.last_rate, cell: (r) => (r.last_rate ? formatINR(r.last_rate) : <span className="text-subtle">-</span>), hideBelow: 'md' },
    ...(manage
      ? [
          {
            id: 'actions',
            header: '',
            align: 'right' as const,
            width: '3.5rem',
            cell: (r: Item) => (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Remove ${r.item_code}`}
                onClick={(e) => {
                  e.stopPropagation()
                  setRemoving(r)
                }}
              >
                <Trash2 />
              </Button>
            ),
          },
        ]
      : []),
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="item" id={r.id} label={String(r.item_code)} noun="item" /> },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Store"
        title="Item Master"
        description="Every material and deliverable, each with one code that follows it through orders, budgets and bills."
        actions={
          <>
            <Button variant="outline" asChild>
              <a href="/api/erp/items.xlsx">
                <Download /> Excel
              </a>
            </Button>
            {manage && (
              <>
                <Button variant="outline" onClick={() => setImporting(true)}>
                  <FileUp /> Import from Excel
                </Button>
                <Button onClick={() => setAdding(true)}>
                  <Plus /> Add items
                </Button>
              </>
            )}
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs
          label="Kind"
          value={tab}
          onChange={setTab}
          items={[
            { value: '', label: 'All', count: counts ? counts.RM + counts.FG : undefined },
            { value: 'RM', label: 'Raw materials', count: counts?.RM },
            { value: 'FG', label: 'Finished goods', count: counts?.FG },
          ]}
        />
        <div className="min-w-[14rem] flex-1 sm:max-w-sm">
          <Input type="search" aria-label="Search items" placeholder="Search by code or name" value={q} onChange={(e) => setQ(e.target.value)} leading={<Search />} />
        </div>
      </div>

      <DataTable
        label="Items"
        rows={items.data?.items ?? []}
        columns={columns}
        rowKey={(r) => r.id}
        loading={items.isPending}
        onRowClick={manage ? setEditing : undefined}
        empty={search ? `Nothing matches "${search}".` : 'No items yet. Add some, or bring them in from Excel.'}
        footer={items.data && items.data.items.length >= 500 ? 'Showing the newest 500 - search to narrow it down.' : undefined}
      />

      <AddItemsModal open={adding} onOpenChange={setAdding} vocab={vocab.data} />
      <ImportItemsModal open={importing} onOpenChange={setImporting} vocab={vocab.data} />
      <EditItemModal item={editing} onClose={() => setEditing(null)} vocab={vocab.data} />
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={`Remove ${removing?.item_code ?? ''}?`}
        description={removing ? `${removing.item_name} is deleted for good. This only works while no order or budget line uses it.` : undefined}
        confirmLabel="Remove"
        tone="danger"
        loading={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing)
        }}
      />
    </>
  )
}
