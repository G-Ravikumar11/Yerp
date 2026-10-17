import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, FileSpreadsheet } from 'lucide-react'
import { Badge, Button, Field, Input, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { StorePicker } from '../shared'
import { useStoreMeta } from '@/api/store'
import { money, qs, qty, useItemPosition, useLedger, type LedgerRow } from './api'

const dmy = (iso: string) => new Date(iso + 'T00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })

/** Store > Stock enquiry > Stock card: every movement of an item, with the balance after each, so the page adds up. */
export default function StockCardPage() {
  const [params, setParams] = useSearchParams()
  const store = Number(params.get('store') || 0)
  const item = Number(params.get('item') || 0)
  const [range, setRange] = useState({ from_date: '', to_date: '', movement_type: '' })
  const meta = useStoreMeta()
  const pos = useItemPosition(item)
  const card = useLedger({ store_id: store, item_id: item, ...range })
  const uom = pos.data?.item.base_uom ?? ''

  const columns: TableColumn<LedgerRow>[] = [
    { id: 'date', header: 'Date', width: '7.5rem', cell: (r) => dmy(r.txn_date) },
    { id: 'store', header: 'Store', width: '5rem', hideBelow: 'md', cell: (r) => <span className="font-mono text-[13px]">{r.store_code}</span> },
    {
      id: 'move',
      header: 'Movement',
      cell: (r) => (
        <div>
          <span className="font-medium">{r.movement_type.replace(/_/g, ' ')}</span>{' '}
          {r.is_reversal && <Badge tone="warning">Reversal</Badge>}
          {r.reversed && <Badge tone="danger">Reversed</Badge>}
          <div className="text-xs text-muted-foreground">{r.ref_doc_type} #{r.ref_doc_id}{r.project ? ` - ${r.project}` : ''}{r.remarks ? ` - ${r.remarks}` : ''}</div>
        </div>
      ),
    },
    { id: 'in', header: 'In', align: 'right', width: '6.5rem', cell: (r) => (Number(r.qty_in) ? qty(r.qty_in) : '') },
    { id: 'out', header: 'Out', align: 'right', width: '6.5rem', cell: (r) => (Number(r.qty_out) ? qty(r.qty_out) : '') },
    { id: 'rate', header: 'Rate', align: 'right', width: '6.5rem', hideBelow: 'md', cell: (r) => money(r.rate) },
    { id: 'value', header: 'Value', align: 'right', width: '7.5rem', hideBelow: 'sm', cell: (r) => money(r.value) },
    { id: 'bal', header: 'Balance', align: 'right', width: '7.5rem', cell: (r) => <span className="font-medium">{qty(r.running_qty)}</span> },
  ]

  if (!item) {
    return (
      <div>
        <Link to="/store/hub/enquiry" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Stock position</Link>
        <p className="text-sm text-muted-foreground">Open an item from the stock position to see its stock card.</p>
      </div>
    )
  }
  return (
    <div>
      <Link to="/store/hub/enquiry" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Stock position</Link>
      <h2 className="text-lg font-semibold">{pos.data?.item.name ?? 'Stock card'} <span className="font-mono text-sm font-normal text-muted-foreground">{pos.data?.item.code}</span></h2>
      {pos.data && (
        <p className="mb-4 mt-1 text-sm text-muted-foreground">
          {qty(pos.data.total_qty)} {uom} held in all, worth {money(pos.data.total_value)}
          {pos.data.also_in.length > 0 && <> ({pos.data.also_in.map((a) => `${qty(a.qty)} ${a.uom}`).join(', ')})</>}
        </p>
      )}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Store" htmlFor="sc-store" className="w-56">
          <StorePicker id="sc-store" value={store || null} placeholder="All my stores" onChange={(id) => setParams((p) => { const n = new URLSearchParams(p); if (id) n.set('store', String(id)); else n.delete('store'); return n })} />
        </Field>
        <Field label="From" htmlFor="sc-from" className="w-40"><Input id="sc-from" type="date" value={range.from_date} onChange={(e) => setRange({ ...range, from_date: e.target.value })} /></Field>
        <Field label="To" htmlFor="sc-to" className="w-40"><Input id="sc-to" type="date" min={range.from_date || undefined} value={range.to_date} onChange={(e) => setRange({ ...range, to_date: e.target.value })} /></Field>
        <Field label="Movement" htmlFor="sc-type" className="w-52">
          <Select id="sc-type" value={range.movement_type} placeholder="All" onChange={(e) => setRange({ ...range, movement_type: e.target.value })} options={(meta.data?.movement_types ?? []).map((m) => ({ value: m, label: m.replace(/_/g, ' ') }))} />
        </Field>
        <Button variant="outline" className="ml-auto" asChild><a href={`/api/store/enquiry/ledger/export${qs({ store_id: store, item_id: item, ...range })}`}><FileSpreadsheet /> Excel</a></Button>
      </div>
      {card.isError ? <p role="alert" className="text-sm text-danger">Could not load the stock card.</p> : (
        <DataTable
          label="Stock card"
          rows={card.data?.items ?? []}
          loading={card.isPending}
          columns={columns}
          rowKey={(r) => r.id}
          rowClassName={(r) => (r.is_reversal ? 'bg-warning-soft/40' : undefined)}
          empty="No movements in this period."
          footer={card.data && store ? (
            <p className="px-3 py-2 text-sm">
              Opening <b>{qty(card.data.opening_qty ?? '0')}</b> + in <b>{qty(card.data.qty_in)}</b> - out <b>{qty(card.data.qty_out)}</b> = closing <b>{qty(card.data.closing_qty ?? '0')}</b> {uom}
            </p>
          ) : undefined}
        />
      )}
    </div>
  )
}
