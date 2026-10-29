import { Pencil } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button } from '@/components/ui'
import type { RfqLine, Statement } from '@/api/rfq'
import { formatQty } from '@/lib/format'
import { formatINR } from '@/lib/utils'

/** What the enquiry asks for, each item with its lowest quote so far and, once awarded, who got it and on which order. */
export function ItemsTab({ d, onEdit }: { d: Statement; onEdit: () => void }) {
  const open = d.rfq.status === 'OPEN'
  const awarded = d.rfq.status === 'AWARDED'
  const columns: TableColumn<RfqLine>[] = [
    { id: 'no', header: '#', width: '3rem', cell: (_l, i) => <span className="text-muted-foreground">{i + 1}</span> },
    {
      id: 'item',
      header: 'Item',
      cell: (l) => (
        <div className="min-w-0">
          <div className="font-medium">{l.description}</div>
          {l.item_code && <div className="font-mono text-xs text-muted-foreground">{l.item_code}</div>}
        </div>
      ),
    },
    { id: 'qty', header: 'Quantity', width: '9rem', align: 'right', cell: (l) => <span>{formatQty(l.qty)} <span className="text-muted-foreground">{l.uom}</span></span> },
    awarded
      ? { id: 'won', header: 'Ordered from', width: '16rem', cell: (l) => (l.awarded_supplier ? <div><div className="truncate">{l.awarded_supplier}</div><div className="text-xs text-muted-foreground">{formatINR(l.awarded_rate)} / {l.uom || 'unit'}{l.po_number && <> · <span className="font-mono">{l.po_number}</span></>}</div></div> : '-') }
      : { id: 'low', header: 'Lowest quote', width: '16rem', cell: (l) => (l.lowest ? <div><div className="tabular">{formatINR(l.lowest_rate)} <span className="text-xs text-muted-foreground">/ {l.uom || 'unit'}</span></div><div className="truncate text-xs text-muted-foreground">{l.lowest}{l.offers.length > 1 ? ` · ${l.offers.length} quoted` : ''}</div></div> : <span className="text-muted-foreground">Not quoted yet</span>) },
  ]
  return (
    <section aria-label="Items" className="grid gap-3">
      {open && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">{d.suppliers.length ? 'Suppliers have priced these items, so they are fixed now.' : 'Change the items until the first quote comes in.'}</p>
          <Button variant="outline" onClick={onEdit}><Pencil /> Edit the enquiry</Button>
        </div>
      )}
      <DataTable label="Enquiry items" rows={d.lines} columns={columns} rowKey={(l) => l.rfq_line_id} />
      {d.rfq.notes && (
        <div className="rounded-xl border border-border bg-card px-4 py-3 text-sm">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Notes for suppliers</p>
          <p className="mt-1 whitespace-pre-line">{d.rfq.notes}</p>
        </div>
      )}
    </section>
  )
}
