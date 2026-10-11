import { useState } from 'react'
import { Printer } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Select, Stat, StatGrid } from '@/components/ui'
import { useConsumption, usePlacedOrders, type Consumption } from '@/api/stock'
import { formatINR } from '@/lib/utils'

type Line = Consumption['lines'][number]

/** What the contract was priced on, against what the site actually drew from the store. */
export default function ConsumptionPage() {
  const orders = usePlacedOrders()
  const [pick, setPick] = useState(0)
  const wo = pick || orders.data?.[0]?.id || 0
  const q = useConsumption(wo)
  const s = q.data?.summary
  const columns: TableColumn<Line>[] = [
    { id: 'item', header: 'Item', cell: (l) => <div><span className="font-mono font-semibold">{l.item_code}</span><div className="text-xs text-muted-foreground">{l.item_name}</div></div> },
    { id: 'plan', header: 'Costed', align: 'right', cell: (l) => l.planned_qty },
    { id: 'drawn', header: 'Drawn', align: 'right', cell: (l) => <div>{l.issued_qty}<div className="mt-1 h-1.5 w-20 overflow-hidden rounded-full bg-muted"><div className={`h-full ${l.over_consumed ? 'bg-warning' : 'bg-primary'}`} style={{ width: `${Math.max(0, Math.min(100, l.percent_used))}%` }} /></div></div> },
    { id: 'var', header: 'Difference', align: 'right', cell: (l) => <span className={l.over_consumed ? 'font-semibold text-warning' : ''}>{l.variance_qty > 0 ? '+' : ''}{l.variance_qty}</span> },
    { id: 'val', header: 'Value', hideBelow: 'md', align: 'right', cell: (l) => formatINR(l.variance_value) },
    { id: 'st', header: '', cell: (l) => (l.unplanned ? <Badge tone="danger" dot>never budgeted</Badge> : l.over_consumed ? <Badge tone="warning" dot>over</Badge> : <Badge tone="success" dot>within</Badge>) },
  ]
  return (
    <>
      <PageHeader eyebrow="Store" title="Material Used vs Costed" description="What the contract was priced on, against what the site actually drew." actions={<Button variant="outline" onClick={() => window.print()}><Printer /> Print</Button>} />
      <div className="mb-6 max-w-md"><Select aria-label="Work order" value={wo || ''} disabled={orders.isPending} placeholder={orders.isPending ? 'Loading...' : orders.data?.length ? undefined : 'No placed orders yet'} onChange={(e) => setPick(Number(e.target.value))} options={(orders.data ?? []).map((w) => ({ value: w.id, label: `${w.number} - ${w.job_name}` }))} /></div>
      <StatGrid>
        <Stat label="Costed on" value={formatINR(s?.planned_value ?? 0)} loading={q.isPending && wo > 0} />
        <Stat label="Actually drawn" value={formatINR(s?.issued_value ?? 0)} loading={q.isPending && wo > 0} />
        <Stat label="Difference" value={formatINR(s?.variance_value ?? 0)} loading={q.isPending && wo > 0} />
        <Stat label="Items over-consumed" value={s?.lines_over_consumed ?? 0} tone={s?.lines_over_consumed ? 'warning' : undefined} loading={q.isPending && wo > 0} />
        <Stat label="Never budgeted" value={s?.unplanned_items ?? 0} tone={s?.unplanned_items ? 'danger' : undefined} loading={q.isPending && wo > 0} />
      </StatGrid>
      <DataTable label="Consumption" rows={q.data?.lines ?? []} columns={columns} rowKey={(l) => l.item_code} loading={q.isPending && wo > 0} empty="Nothing costed or drawn on this order." />
    </>
  )
}
