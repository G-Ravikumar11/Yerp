import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useNavigate } from 'react-router-dom'
import { FileSpreadsheet } from 'lucide-react'
import { Badge, Button, Field, Input, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { StorePicker } from '../shared'
import { useStoreMeta } from '@/api/store'
import { money, qs, qty, STATUS_LABEL, STATUS_TONE, usePosition, type BalanceRow } from './api'

/** Store > Stock enquiry: what is held, store by store and item by item. A row opens that item's stock card. */
export default function StockPositionPage() {
  const nav = useNavigate()
  const meta = useStoreMeta()
  const [params] = useSearchParams()
  // A link (a scanned bin tag) may name the store and the search.
  const [f, setF] = useState({ store_id: Number(params.get('store') || 0), q: params.get('q') ?? '', category: '', status: '', include_zero: false })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const pos = usePosition(f)

  const columns: TableColumn<BalanceRow>[] = [
    { id: 'store', header: 'Store', width: '6rem', sort: (r) => r.store_code, cell: (r) => <span className="font-mono text-[13px]">{r.store_code}</span> },
    { id: 'item', header: 'Item', sort: (r) => r.item_name, cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'cat', header: 'Category', width: '8rem', hideBelow: 'md', cell: (r) => r.category ?? '-' },
    { id: 'qty', header: 'Quantity', align: 'right', width: '8rem', sort: (r) => Number(r.qty), cell: (r) => <span>{qty(r.qty)} <span className="text-muted-foreground">{r.base_uom}</span></span> },
    { id: 'free', header: 'Free', align: 'right', width: '8rem', hideBelow: 'md', sort: (r) => Number(r.available ?? r.qty), cell: (r) => (Number(r.reserved ?? 0) > 0 ? <span title={`${qty(r.reserved ?? '0')} ${r.base_uom} is promised to approved indents`}>{qty(r.available ?? '0')} <span className="text-muted-foreground">({qty(r.reserved ?? '0')} reserved)</span></span> : <span className="text-muted-foreground">{qty(r.available ?? r.qty)}</span>) },
    { id: 'rate', header: 'Avg rate', align: 'right', width: '7rem', hideBelow: 'sm', sort: (r) => Number(r.avg_rate), cell: (r) => money(r.avg_rate) },
    { id: 'value', header: 'Value', align: 'right', width: '8rem', sort: (r) => Number(r.value), cell: (r) => money(r.value) },
    { id: 'status', header: 'Level', width: '9rem', cell: (r) => <Badge tone={STATUS_TONE[r.status]} dot>{STATUS_LABEL[r.status]}</Badge> },
  ]

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Store" htmlFor="sp-store" className="w-56"><StorePicker id="sp-store" value={f.store_id || null} placeholder="All my stores" onChange={(id) => set('store_id', id ?? 0)} /></Field>
        <Field label="Search" htmlFor="sp-q" className="w-52"><Input id="sp-q" value={f.q} onChange={(e) => set('q', e.target.value)} placeholder="Item code or name" /></Field>
        <Field label="Category" htmlFor="sp-cat" className="w-40">
          <Select id="sp-cat" value={f.category} placeholder="Any" onChange={(e) => set('category', e.target.value)} options={(meta.data?.item_categories ?? []).map((c) => ({ value: c, label: c }))} />
        </Field>
        <Field label="Level" htmlFor="sp-status" className="w-40">
          <Select id="sp-status" value={f.status} placeholder="Any" onChange={(e) => set('status', e.target.value)} options={Object.entries(STATUS_LABEL).map(([v, l]) => ({ value: v, label: l }))} />
        </Field>
        <label className="flex items-center gap-2 pb-2.5 text-sm"><input type="checkbox" checked={f.include_zero} onChange={(e) => set('include_zero', e.target.checked)} /> Show nil stock</label>
        <Button variant="outline" className="ml-auto" asChild><Link to="/store/hub/enquiry/batches">Batches & quality holds</Link></Button>
        <Button variant="outline" asChild><a href={`/api/store/enquiry/balances/export${qs(f)}`}><FileSpreadsheet /> Excel</a></Button>
      </div>
      {pos.data && (
        <p className="mb-3 text-sm text-muted-foreground" role="status">
          {pos.data.total} {pos.data.total === 1 ? 'line' : 'lines'}, worth <span className="font-semibold text-foreground">{money(pos.data.total_value)}</span>
          {pos.data.low > 0 && <> - <span className="text-warning">{pos.data.low} at or below the reorder level</span></>}
        </p>
      )}
      {pos.isError ? <p role="alert" className="text-sm text-danger">Could not load the stock.</p> : (
        <DataTable label="Stock position" rows={pos.data?.items ?? []} loading={pos.isPending} columns={columns} rowKey={(r) => `${r.store_id}-${r.item_id}`}
          onRowClick={(r) => nav(`/store/hub/enquiry/card?store=${r.store_id}&item=${r.item_id}`)} empty="No stock matches. Stock appears here once it has been received." />
      )}
    </div>
  )
}
