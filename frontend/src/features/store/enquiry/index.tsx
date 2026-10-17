import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Badge, Card, Input, Select, SkeletonRows, Tabs } from '@/components/ui'
import { storeGet, useStoreMeta, useStoreOptions } from '@/api/store'
import { StoreShell } from '../StoreShell'

/** Store > Stock enquiry. What each store holds (/stock) and every movement behind it (/ledger). */
interface StockRow { store_id: number; store_code: string; item_id: number; item_code: string; item_name: string; base_uom: string; qty: string; avg_rate: string; value: string; reorder_level: string; below_reorder: boolean }
interface LedgerRow { id: number; txn_date: string; store_code: string; item_code: string; item_name: string; movement_type: string; qty_in: string; qty_out: string; rate: string; value: string; running_qty: string; ref_doc_type: string; ref_doc_id: number; reversal_of_id: number | null; remarks: string }

const money = (v: string) => Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const qty = (v: string) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })

export default function EnquiryIndex() {
  const [tab, setTab] = useState<'stock' | 'ledger'>('stock')
  const [storeId, setStoreId] = useState('')
  const stores = useStoreOptions()
  return (
    <StoreShell slice="enquiry">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Tabs label="Enquiry" value={tab} onChange={setTab} items={[{ value: 'stock', label: 'Stock on hand' }, { value: 'ledger', label: 'Movements' }]} />
        <Select className="w-56" value={storeId} placeholder="All my stores" options={(stores.data ?? []).map((s) => ({ value: s.id, label: `${s.code} · ${s.name}` }))} onChange={(e) => setStoreId(e.target.value)} />
      </div>
      {tab === 'stock' ? <Stock storeId={storeId} /> : <Ledger storeId={storeId} />}
    </StoreShell>
  )
}

function Stock({ storeId }: { storeId: string }) {
  const [q, setQ] = useState('')
  const [low, setLow] = useState(false)
  const res = useQuery({
    queryKey: ['store', 'enquiry', 'stock', storeId, q, low],
    queryFn: () => storeGet<{ rows: StockRow[]; total: number; total_value: string; frozen_store_ids: number[] }>('enquiry', `/stock?store_id=${storeId || 0}&q=${encodeURIComponent(q)}&below_reorder=${low}`),
  })
  const rows = res.data?.rows ?? []
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Input className="max-w-xs" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search item code or name" />
        <label className="flex items-center gap-2 text-sm text-muted-foreground"><input type="checkbox" checked={low} onChange={(e) => setLow(e.target.checked)} /> Only at or below reorder level</label>
        {res.data && <span className="ml-auto text-sm text-muted-foreground">{res.data.total} lines · ₹{money(res.data.total_value)}</span>}
      </div>
      {res.isLoading ? <SkeletonRows rows={6} cols={6} /> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Store</th><th className="p-3">Item</th><th className="p-3 text-right">Quantity</th><th className="p-3 text-right">Avg rate</th><th className="p-3 text-right">Value</th><th className="p-3" /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.store_id}-${r.item_id}`} className="border-b border-border last:border-0">
                  <td className="p-3 font-mono">{r.store_code}</td><td className="p-3"><span className="font-mono text-xs text-muted-foreground">{r.item_code}</span> {r.item_name}</td>
                  <td className="p-3 text-right">{qty(r.qty)} {r.base_uom}</td><td className="p-3 text-right">{money(r.avg_rate)}</td><td className="p-3 text-right">{money(r.value)}</td>
                  <td className="p-3">{res.data?.frozen_store_ids.includes(r.store_id) && <Badge tone="warning">Frozen</Badge>} {r.below_reorder && <Badge tone="danger">Reorder</Badge>}</td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={6} className="p-6 text-center text-muted-foreground">No stock found.</td></tr>}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}

function Ledger({ storeId }: { storeId: string }) {
  const meta = useStoreMeta()
  const [type, setType] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(0)
  const size = 50
  const res = useQuery({
    queryKey: ['store', 'enquiry', 'ledger', storeId, type, from, to, page],
    queryFn: () => storeGet<{ rows: LedgerRow[]; total: number }>('enquiry', `/ledger?store_id=${storeId || 0}&movement_type=${type}&from_date=${from}&to_date=${to}&limit=${size}&offset=${page * size}`),
  })
  const rows = res.data?.rows ?? []
  const total = res.data?.total ?? 0
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <Select className="w-52" value={type} placeholder="All movement types" options={(meta.data?.movement_types ?? []).map((m) => ({ value: m, label: m }))} onChange={(e) => { setType(e.target.value); setPage(0) }} />
        <Input className="w-40" type="date" aria-label="From date" value={from} onChange={(e) => { setFrom(e.target.value); setPage(0) }} />
        <Input className="w-40" type="date" aria-label="To date" value={to} onChange={(e) => { setTo(e.target.value); setPage(0) }} />
      </div>
      {res.isLoading ? <SkeletonRows rows={8} cols={7} /> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Date</th><th className="p-3">Store</th><th className="p-3">Item</th><th className="p-3">Movement</th><th className="p-3 text-right">In</th><th className="p-3 text-right">Out</th><th className="p-3 text-right">Value</th><th className="p-3 text-right">Balance</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0">
                  <td className="p-3 whitespace-nowrap">{r.txn_date}</td><td className="p-3 font-mono">{r.store_code}</td><td className="p-3">{r.item_name}</td>
                  <td className="p-3">{r.movement_type} {r.reversal_of_id && <Badge tone="warning">Reversal</Badge>}<div className="text-xs text-muted-foreground">{r.ref_doc_type} #{r.ref_doc_id}</div></td>
                  <td className="p-3 text-right">{Number(r.qty_in) ? qty(r.qty_in) : ''}</td><td className="p-3 text-right">{Number(r.qty_out) ? qty(r.qty_out) : ''}</td>
                  <td className="p-3 text-right">{money(r.value)}</td><td className="p-3 text-right">{qty(r.running_qty)}</td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={8} className="p-6 text-center text-muted-foreground">No movements.</td></tr>}
            </tbody>
          </table>
        </Card>
      )}
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>{total ? `${page * size + 1}–${Math.min((page + 1) * size, total)} of ${total}` : ''}</span>
        <span className="flex gap-3"><button className="hover:text-foreground disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><button className="hover:text-foreground disabled:opacity-40" disabled={(page + 1) * size >= total} onClick={() => setPage(page + 1)}>Next</button></span>
      </div>
    </div>
  )
}
