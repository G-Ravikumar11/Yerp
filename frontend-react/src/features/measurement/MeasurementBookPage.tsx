import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { FileDown, FileUp, Ruler, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, ConfirmDialog, Select, Stat, StatGrid } from '@/components/ui'
import { deleteEntry, mbKeys, useMeasurementBook, type MbEntry, type MbLine } from '@/api/mb'
import { useOrders } from '@/api/orders'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, formatQty } from '@/lib/format'
import { cn, compactINR, formatINR } from '@/lib/utils'
import { ImportBookModal } from './ImportBookModal'
import { MeasureModal } from './MeasureModal'

/** A thin bar showing how much of an item is measured. Red past what was ordered. */
function Progress({ percent, over }: { percent: number; over: boolean }) {
  return (
    <div className="mt-1 h-1.5 w-28 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={Math.round(percent)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cn('h-full rounded-full transition-[width] duration-500', over ? 'bg-danger' : 'bg-primary')} style={{ width: `${Math.min(100, percent)}%` }} />
    </div>
  )
}

export default function MeasurementBookPage() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const orders = useOrders()
  const live = (orders.data?.orders ?? []).filter((o) => o.status === 'APPROVED' || o.status === 'EXECUTED')
  const chosen = Number(params.get('order')) || live[0]?.id || 0
  const book = useMeasurementBook(chosen)
  const [measuring, setMeasuring] = useState<MbLine | null>(null)
  const [importing, setImporting] = useState(false)
  const [removing, setRemoving] = useState<MbEntry | null>(null)
  const record = can('site.record')

  const remove = useAction((e: MbEntry) => deleteEntry(e.id), { invalidate: [mbKeys.all, ['subbills']], onSuccess: () => setRemoving(null), onError: () => setRemoving(null) })

  const lines = book.data?.lines ?? []
  const byItem = new Map(lines.map((l) => [l.item_id, l]))
  const entries = book.data?.entries ?? []
  const filters = useListFilters(entries, {
    search: (e) => [e.activity_no, byItem.get(e.item_id)?.description, e.location, e.mb_ref, e.remarks, e.recorded_by_name, e.dimensions.map((d) => d.particulars).join(' ')].join(' '),
    date: (e) => e.measured_on,
  })
  const s = book.data?.summary

  const itemColumns: TableColumn<MbLine>[] = [
    {
      id: 'activity',
      header: 'Activity',
      cell: (l) => (
        <div className={cn('max-w-md', l.is_header && 'font-semibold')}>
          <span className="mr-2 font-mono text-xs text-muted-foreground">{l.activity_no}</span>
          {l.description}
        </div>
      ),
    },
    { id: 'ordered', header: 'Ordered', align: 'right', cell: (l) => (l.is_header ? '' : `${formatQty(l.ordered_qty)} ${l.uom}`) },
    {
      id: 'measured',
      header: 'Measured',
      align: 'right',
      cell: (l) =>
        l.is_header ? (
          ''
        ) : (
          <div className="flex flex-col items-end">
            <span className={cn('font-medium', !!l.over_measured && 'text-danger')}>{formatQty(l.measured_to_date)}</span>
            <Progress percent={l.percent_measured ?? 0} over={!!l.over_measured} />
          </div>
        ),
    },
    { id: 'left', header: 'Still to do', align: 'right', hideBelow: 'md', cell: (l) => (l.is_header ? '' : formatQty(Math.max(0, l.balance_to_measure ?? 0))) },
    { id: 'billed', header: 'Billed', align: 'right', hideBelow: 'lg', cell: (l) => (l.is_header ? '' : formatQty(l.billed_to_date)) },
    { id: 'unbilled', header: 'Unbilled', align: 'right', hideBelow: 'lg', cell: (l) => (l.is_header ? '' : formatQty(l.unbilled)) },
    { id: 'value', header: 'Unbilled value', align: 'right', hideBelow: 'xl', cell: (l) => (l.is_header ? '' : formatINR((l.unbilled ?? 0) * (l.rate ?? 0))) },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (l) =>
        !l.is_header && record ? (
          <Button size="sm" onClick={() => setMeasuring(l)}>
            <Ruler /> Measure
          </Button>
        ) : null,
    },
  ]

  const entryColumns: TableColumn<MbEntry>[] = [
    { id: 'date', header: 'Date', sort: (e) => e.measured_on, cell: (e) => formatDate(e.measured_on) },
    {
      id: 'item',
      header: 'Activity',
      cell: (e) => (
        <div className="max-w-xs">
          <div className="truncate">
            <span className="mr-1.5 font-mono text-xs text-muted-foreground">{e.activity_no}</span>
            {byItem.get(e.item_id)?.description}
          </div>
          {e.location && <div className="truncate text-xs text-muted-foreground">{e.location}</div>}
        </div>
      ),
    },
    {
      id: 'dims',
      header: 'Particulars',
      hideBelow: 'lg',
      cell: (e) => {
        const parts = e.dimensions.filter((d) => !d.is_heading)
        return parts.length ? (
          <span className="line-clamp-2 max-w-sm text-[13px] text-muted-foreground" title={e.dimensions.map((d) => d.particulars).filter(Boolean).join(', ')}>
            {parts.map((d) => d.particulars || 'line').join(', ')}
            {e.multiplier !== 1 && <span className="ml-1 text-foreground">× {e.multiplier} blocks</span>}
          </span>
        ) : (
          <span className="text-subtle">a total</span>
        )
      },
    },
    { id: 'qty', header: 'Quantity', align: 'right', sort: (e) => e.quantity, cell: (e) => <span className={cn('font-medium', e.quantity < 0 && 'text-danger')}>{formatQty(e.quantity)}</span> },
    { id: 'ref', header: 'Ref', hideBelow: 'xl', cell: (e) => <span className="font-mono text-xs">{e.mb_ref || '-'}</span> },
    { id: 'who', header: 'Recorded by', hideBelow: 'xl', cell: (e) => e.recorded_by_name },
    { id: 'billed', header: '', cell: (e) => (e.billed ? <Badge tone="info">Billed</Badge> : null) },
    {
      id: 'del',
      header: '',
      align: 'right',
      width: '3rem',
      cell: (e) =>
        record && !e.billed ? (
          <Button variant="ghost" size="icon-sm" aria-label="Remove this entry" onClick={() => setRemoving(e)}>
            <Trash2 />
          </Button>
        ) : null,
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Subcontractors"
        title="Measurement Book"
        description="What the gang has built, measured line by line. Only measured work can be billed, and nothing is billed twice."
        actions={
          <>
            <Button variant="outline" asChild>
              <a href="/api/sub-mb/template.xlsx">
                <FileDown /> MB template
              </a>
            </Button>
            {record && chosen > 0 && (
              <Button onClick={() => setImporting(true)}>
                <FileUp /> Import MB from Excel
              </Button>
            )}
          </>
        }
      />

      <div className="mb-6 max-w-2xl">
        <Select
          aria-label="Work order"
          value={chosen || ''}
          onChange={(e) => setParams(e.target.value ? { order: e.target.value } : {})}
          placeholder={orders.isPending ? 'Loading...' : 'No approved work orders yet'}
          options={live.map((o) => ({ value: o.id, label: `${o.wo_number} - ${o.contractor || 'no gang'} · ${o.project}` }))}
        />
      </div>

      {chosen > 0 && (
        <>
          <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
            <Stat label="Order value" value={compactINR(s?.ordered_value)} loading={book.isPending} />
            <Stat label="Work measured" value={compactINR(s?.measured_value)} loading={book.isPending} />
            <Stat label="Measured, not billed" value={compactINR(s?.unbilled_value)} loading={book.isPending} />
            <Stat label="Items over the order" value={s?.lines_over_measured ?? 0} tone={s?.lines_over_measured ? 'danger' : undefined} loading={book.isPending} />
          </StatGrid>

          <h2 className="mb-3 text-lg font-semibold">Items on the order - measure each one</h2>
          <DataTable label="Items on the order" rows={lines} columns={itemColumns} rowKey={(l) => l.item_id} loading={book.isPending} empty="This order has no schedule lines." className="mb-8" />

          <h2 className="mb-3 text-lg font-semibold">Measurement entries</h2>
          <FilterBar filters={filters} placeholder="Search entries..." />
          <DataTable
            label="Measurement entries"
            rows={filters.filtered}
            columns={entryColumns}
            rowKey={(e) => e.id}
            loading={book.isPending}
            empty={filters.active ? 'Nothing matches those filters.' : 'Nothing measured yet.'}
          />

          <MeasureModal orderId={chosen} line={measuring} onClose={() => setMeasuring(null)} />
          <ImportBookModal orderId={chosen} open={importing} onOpenChange={setImporting} />
          <ConfirmDialog
            open={!!removing}
            onOpenChange={(o) => !o && setRemoving(null)}
            title="Remove this measurement?"
            description={removing ? `${formatQty(removing.quantity)} on ${formatDate(removing.measured_on)}. A measurement that has been billed can only be corrected with another entry.` : undefined}
            confirmLabel="Remove"
            tone="danger"
            loading={remove.isPending}
            onConfirm={() => {
              if (removing) remove.mutate(removing)
            }}
          />
        </>
      )}
    </>
  )
}
