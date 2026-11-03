import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { FileSpreadsheet } from 'lucide-react'
import { Button, Card, Select, Stat, StatGrid } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { formatDate } from '@/lib/format'
import { useStoreMeta } from '@/api/store'
import { qs, qty } from '../enquiry/api'
import { inLakhs, isLow, matching, useStock, type StockRow } from './api'
import { RegisterFilters, RegisterHeader } from './RegisterParts'

/** Store > Stock Register: what every store holds, its levels and when it last came in. A row opens the item's stock card. */
export function StockRegister({ embedded, storeId: fixed }: { embedded?: boolean; storeId?: number }) {
  const nav = useNavigate()
  const meta = useStoreMeta()
  const [params] = useSearchParams()
  // A link (a scanned bin tag) may name the store and the search.
  const [own, setStoreId] = useState(Number(params.get('store') || 0))
  const storeId = fixed ?? own
  const [q, setQ] = useState(params.get('q') ?? '')
  const [category, setCategory] = useState('')
  const [lowOnly, setLowOnly] = useState(false)
  const stock = useStock({ store_id: storeId, category })
  const fromDesk = fixed === undefined ? '' : '&from=desk'
  const all = stock.data?.items ?? []
  const rows = matching(all, q, (r) => [r.item_name, r.item_code, r.category, r.store_name, r.store_code]).filter((r) => !lowOnly || isLow(r))
  const items = new Set(all.map((r) => r.item_id)).size
  const cats = new Set(all.map((r) => r.category).filter(Boolean)).size
  const low = all.filter(isLow).length

  const columns: TableColumn<StockRow>[] = [
    { id: 'code', header: 'ID', width: '6rem', sort: (r) => r.item_code, cell: (r) => <span className="font-mono text-[13px]">{r.item_code}</span> },
    { id: 'name', header: 'Material name', sort: (r) => r.item_name, cell: (r) => <span className="font-medium">{r.item_name}</span> },
    { id: 'cat', header: 'Category', width: '7.5rem', hideBelow: 'lg', sort: (r) => r.category ?? '', cell: (r) => r.category ?? '-' },
    { id: 'uom', header: 'Unit', width: '4rem', cell: (r) => r.base_uom },
    { id: 'qty', header: 'In stock', align: 'right', width: '6rem', sort: (r) => Number(r.qty), cell: (r) => <span className={isLow(r) ? 'font-semibold text-danger' : ''}>{qty(r.qty)}</span> },
    { id: 'min', header: 'Min stock', align: 'right', width: '6rem', hideBelow: 'md', sort: (r) => Number(r.min_qty), cell: (r) => (Number(r.min_qty) ? qty(r.min_qty) : '-') },
    { id: 'max', header: 'Max stock', align: 'right', width: '6rem', hideBelow: 'xl', sort: (r) => Number(r.max_qty), cell: (r) => (Number(r.max_qty) ? qty(r.max_qty) : '-') },
    { id: 'last', header: 'Last received', width: '7.5rem', hideBelow: 'lg', sort: (r) => r.last_received ?? '', cell: (r) => (r.last_received ? formatDate(r.last_received) : '-') },
    { id: 'loc', header: 'Location', width: '8rem', hideBelow: 'sm', sort: (r) => r.store_name, cell: (r) => r.store_name },
  ]
  return (
    <div>
      <RegisterHeader embedded={embedded} title="Stock Register" description="Current stock levels for all materials." actions={<>
        <Button variant="outline" asChild><Link to={`/store/hub/enquiry/batches${fromDesk ? '?from=desk' : ''}`}>Batches & quality holds</Link></Button>
        <Button variant="outline" asChild><a href={`/api/store/enquiry/balances/export${qs({ store_id: storeId, category })}`}><FileSpreadsheet /> Excel</a></Button>
      </>} />
      {!embedded && (
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Total items" value={items.toLocaleString('en-IN')} loading={stock.isPending} />
        <Stat label="Total value" value={inLakhs(Number(stock.data?.total_value ?? 0))} tone="success" loading={stock.isPending} />
        <Stat label="Low stock count" value={low} tone={low ? 'danger' : undefined} loading={stock.isPending} onClick={() => setLowOnly(!lowOnly)} active={lowOnly} sub={lowOnly ? 'Showing low stock only' : 'Show only these'} />
        <Stat label="Categories" value={cats} loading={stock.isPending} />
      </StatGrid>
      )}
      <Card className="p-4">
        <RegisterFilters q={q} onQ={setQ} storeId={storeId} onStore={fixed === undefined ? setStoreId : undefined}>
          <div className="w-full sm:w-44"><Select aria-label="Category" value={category} placeholder="Any category" onChange={(e) => setCategory(e.target.value)} options={(meta.data?.item_categories ?? []).map((c) => ({ value: c, label: c }))} /></div>
        </RegisterFilters>
        {stock.isError ? <p role="alert" className="text-sm text-danger">Could not load the stock.</p> : (
          <DataTable label="Stock register" rows={rows} loading={stock.isPending} columns={columns} rowKey={(r) => `${r.store_id}-${r.item_id}`}
            onRowClick={(r) => nav(`/store/hub/enquiry/card?store=${r.store_id}&item=${r.item_id}${fromDesk}`)} empty="No stock matches. Stock appears here once it has been received." />
        )}
      </Card>
    </div>
  )
}

export default function StockRegisterPage() {
  return <StockRegister />
}
