import { useState } from 'react'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Stat, StatGrid } from '@/components/ui'
import { useEways, type Eway, type Uncovered } from '@/api/eway'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { EwayModal } from './EwayModal'

/** Goods over the threshold on the road - site transfers, plant, returns - each with its e-way bill. */
export default function EwayPage() {
  const q = useEways()
  const [open, setOpen] = useState<{ id: number | null; transfer: string } | null>(null)
  const s = q.data?.summary
  const need: TableColumn<Uncovered>[] = [
    { id: 'n', header: 'Transfer', cell: (t) => <span className="font-mono">{t.number}</span> },
    { id: 'm', header: 'Moved', cell: (t) => formatDate(t.moved_on) },
    { id: 'f', header: 'From to', cell: (t) => `${t.from_store} to ${t.to_store}` },
    { id: 'v', header: 'Value', align: 'right', cell: (t) => formatINR(t.value) },
    { id: 'a', header: '', align: 'right', cell: (t) => <Button size="sm" onClick={() => setOpen({ id: null, transfer: t.number })}>Draw the e-way bill</Button> },
  ]
  const bills: TableColumn<Eway>[] = [
    { id: 'ref', header: 'Ref', cell: (e) => <div><button type="button" className="font-mono font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setOpen({ id: e.id, transfer: '' })}>{e.number}</button><div className="text-xs text-muted-foreground">{e.source_ref || 'typed'}</div></div> },
    { id: 'ft', header: 'From to', cell: (e) => <div>{e.from.name} to {e.to.name}<div className="text-xs text-muted-foreground">{e.from.pincode} to {e.to.pincode}{e.distance_km ? ` - ${e.distance_km} km` : ''}</div></div> },
    { id: 'val', header: 'Value', hideBelow: 'md', align: 'right', cell: (e) => formatINR(e.total_value) },
    { id: 'veh', header: 'Vehicle', hideBelow: 'lg', cell: (e) => <span className="font-mono">{e.vehicle_no || '-'}</span> },
    { id: 'no', header: 'EWB no.', hideBelow: 'md', cell: (e) => <span className="font-mono">{e.ewb_no || '-'}</span> },
    { id: 'valid', header: 'Valid to', hideBelow: 'xl', cell: (e) => e.valid_upto },
    { id: 'st', header: 'Status', cell: (e) => <Badge tone={e.status === 'GENERATED' ? (e.expired ? 'danger' : 'success') : e.status === 'CANCELLED' ? 'neutral' : 'warning'} dot>{e.expired ? 'Expired' : e.status === 'GENERATED' ? 'Issued' : e.status === 'CANCELLED' ? 'Cancelled' : 'Draft'}</Badge> },
  ]
  return (
    <>
      <PageHeader eyebrow="Store" title="E-way Bills" description="Goods on the road over the threshold - site transfers, plant, returns - each with its e-way bill." actions={<Button onClick={() => setOpen({ id: null, transfer: '' })}><Plus /> E-way bill</Button>} />
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Transfers needing one" value={s?.uncovered ?? 0} tone={s?.uncovered ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Drafts" value={s?.drafts ?? 0} loading={q.isPending} />
        <Stat label="Live on the road" value={s?.live ?? 0} loading={q.isPending} />
        <Stat label="Past their validity" value={s?.expired ?? 0} tone={s?.expired ? 'danger' : undefined} loading={q.isPending} />
      </StatGrid>
      {(q.data?.uncovered_transfers.length ?? 0) > 0 && <section aria-label="Transfers that need one" className="mb-6"><h2 className="mb-2 text-sm font-semibold">Transfers that need one</h2><DataTable label="Transfers that need one" rows={q.data?.uncovered_transfers ?? []} columns={need} rowKey={(t) => t.number} /></section>}
      <h2 className="mb-2 text-sm font-semibold">E-way bills</h2>
      <DataTable label="E-way bills" rows={q.data?.eway_bills ?? []} columns={bills} rowKey={(e) => e.id} onRowClick={(e) => setOpen({ id: e.id, transfer: '' })} loading={q.isPending} empty="None yet. Draw one from a transfer above, or type one for plant or a return." />
      <EwayModal id={open?.id ?? null} fromTransfer={open?.transfer ?? ''} open={!!open} onClose={() => setOpen(null)} />
    </>
  )
}
