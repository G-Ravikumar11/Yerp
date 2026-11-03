import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { TriangleAlert } from 'lucide-react'
import { Button, Card } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { qty } from '../enquiry/api'
import { isLow, levelOf, matching, useStock, type StockRow } from './api'
import { RegisterFilters, RegisterHeader } from './RegisterParts'

/** Store > Low Stock: what is at or under its reorder level (or its minimum), worst first, with how much short it is. */
/** `storeId` given: it sits in the Store Desk, which chooses the store and has the heading. */
export function LowStockList({ storeId: fixed }: { storeId?: number } = {}) {
  const embedded = fixed !== undefined
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [own, setStoreId] = useState(0)
  const storeId = fixed ?? own
  // Nil stock of an item with a level is the most urgent of all, so nil lines are asked for too.
  const stock = useStock({ store_id: storeId, category: '', include_zero: true })
  const low = (stock.data?.items ?? []).filter(isLow)
  const fromDesk = embedded ? '&from=desk' : ''
  const short = (r: StockRow) => Math.max(0, levelOf(r) - Number(r.qty))
  const rows = matching(low, q, (r) => [r.item_name, r.item_code, r.category, r.store_name]).sort((a, b) => Number(a.qty) / levelOf(a) - Number(b.qty) / levelOf(b))
  const columns: TableColumn<StockRow>[] = [
    { id: 'code', header: 'ID', width: '7rem', sort: (r) => r.item_code, cell: (r) => <span className="font-mono text-[13px]">{r.item_code}</span> },
    { id: 'name', header: 'Material name', sort: (r) => r.item_name, cell: (r) => <span className="font-medium">{r.item_name}</span> },
    { id: 'cat', header: 'Category', width: '8rem', hideBelow: 'md', sort: (r) => r.category ?? '', cell: (r) => r.category ?? '-' },
    { id: 'qty', header: 'In stock', align: 'right', width: '7rem', sort: (r) => Number(r.qty), cell: (r) => qty(r.qty) },
    { id: 'min', header: 'Min stock', align: 'right', width: '7rem', sort: (r) => levelOf(r), cell: (r) => qty(String(levelOf(r))) },
    { id: 'short', header: 'Deficit', align: 'right', width: '7rem', sort: short, cell: (r) => <span className="font-semibold text-danger">{qty(String(short(r)))}</span> },
    { id: 'uom', header: 'Unit', width: '5rem', cell: (r) => r.base_uom },
    { id: 'loc', header: 'Location', width: '9rem', hideBelow: 'sm', sort: (r) => r.store_name, cell: (r) => r.store_name },
  ]
  return (
    <div>
      <RegisterHeader embedded={embedded} title="Low Stock Alerts" description="Materials at or below their minimum stock level."
        actions={<Button variant="outline" asChild><Link to="/store/hub/reports/reorder">Reorder report</Link></Button>} />
      {low.length > 0 && (
        <div role="status" className="mb-5 flex items-center gap-2.5 rounded-xl border border-warning/40 bg-warning-soft px-4 py-3 text-sm text-warning">
          <TriangleAlert className="size-5 shrink-0" />
          {low.length} {low.length === 1 ? 'material is' : 'materials are'} at or below the minimum stock level. Reorder now to avoid delays on site.
        </div>
      )}
      <Card className="p-4">
        <RegisterFilters q={q} onQ={setQ} storeId={storeId} onStore={embedded ? undefined : setStoreId} />
        {stock.isError ? <p role="alert" className="text-sm text-danger">Could not load the stock.</p> : (
          <DataTable label="Low stock" rows={rows} loading={stock.isPending} columns={columns} rowKey={(r) => `${r.store_id}-${r.item_id}`}
            onRowClick={(r) => nav(`/store/hub/enquiry/card?store=${r.store_id}&item=${r.item_id}${fromDesk}`)}
            empty="Nothing is low. An item shows here when its stock falls to its reorder level or minimum, set on the item or the store." />
        )}
      </Card>
    </div>
  )
}

export default function LowStockPage() {
  return <LowStockList />
}
