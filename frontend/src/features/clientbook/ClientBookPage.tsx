import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Ruler, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, ConfirmDialog, Select, Stat, StatGrid } from '@/components/ui'
import { bookKeys, clientEntriesUrl, deleteClientEntry, drawRaBill, useClientBook, type ClientBookLine, type ClientEntry } from '@/api/clientBook'
import { useClientOrders, type ClientOrder } from '@/api/clientOrders'
import type { MbLine } from '@/api/mb'
import { MeasureModal } from '@/features/measurement/MeasureModal'
import { QuickMeasure, type QuickMeasureHandle } from '@/features/measurement/QuickMeasure'
import { WorkOrderPicker } from '@/features/measurement/WorkOrderPicker'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, formatQty } from '@/lib/format'
import { cn, compactINR, formatINR } from '@/lib/utils'
import { BillsPanel } from './BillsPanel'
import { Statement } from './Statement'
import { VariationsPanel } from './VariationsPanel'

/** The picker reads a work order by these names; a client order says the same things in its own words. */
const toPick = (o: ClientOrder) => ({ ...o, wo_number: o.number, project: o.job_name, contractor: o.customer_name, subject: o.reference })
type Pick = ReturnType<typeof toPick>

const LAST = 'yerp.client.order'
const remembered = () => {
  try {
    return Number(localStorage.getItem(LAST)) || 0
  } catch {
    return 0
  }
}
const remember = (id: number) => {
  try {
    localStorage.setItem(LAST, String(id))
  } catch {
    // Private window: the book opens on the first order next time.
  }
}

/** The measurement form speaks of "items"; a client line is identified by its line id and finished-goods code. */
const asMbLine = (l: ClientBookLine): MbLine => ({ item_id: l.line_id, activity_no: l.fg_code, item_code: l.fg_code, description: l.description, uom: l.uom, ordered_qty: l.ordered_qty, rate: l.rate, measured_to_date: l.measured_to_date, billed_to_date: l.billed_to_date, unbilled: l.unbilled, balance_to_measure: l.balance_to_measure, percent_measured: l.percent_measured, over_measured: l.over_measured })

function Progress({ percent, over }: { percent: number; over: boolean }) {
  return (
    <div className="mt-1 h-1.5 w-28 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={Math.round(percent)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cn('h-full rounded-full transition-[width] duration-500', over ? 'bg-danger' : 'bg-primary')} style={{ width: `${Math.min(100, percent)}%` }} />
    </div>
  )
}

export default function ClientBookPage() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const orders = useClientOrders()
  // Only an approved order can be measured: its budget and margin have been looked at.
  const listed = (orders.data?.work_orders ?? []).filter((o) => o.approval_status === 'approved').map(toPick)
  const [site, setSite] = useState(0)
  const sites = Array.from(new Map(listed.filter((o) => o.job_id).map((o) => [o.job_id, o.job_name] as const)).entries()).sort((a, b) => a[1].localeCompare(b[1]))
  const shown = site ? listed.filter((o) => o.job_id === site) : listed
  const last = remembered()
  const chosen = Number(params.get('order')) || (listed.some((o) => o.id === last) ? last : 0) || listed[0]?.id || 0
  const order = listed.find((o) => o.id === chosen)
  const book = useClientBook(chosen)
  const quick = useRef<QuickMeasureHandle>(null)
  const [measuring, setMeasuring] = useState<MbLine | null>(null)
  const [removing, setRemoving] = useState<ClientEntry | null>(null)
  const [drawing, setDrawing] = useState(false)
  const record = can('site.record')
  const jobCode = (o: Pick) => o.job_name.split(' ')[0]

  const refresh = [bookKeys.all, ['client-orders']]
  const remove = useAction((e: ClientEntry) => deleteClientEntry(e.id), { invalidate: refresh, onSuccess: () => setRemoving(null), onError: () => setRemoving(null) })
  const draw = useAction(() => drawRaBill(chosen), { invalidate: refresh, onSuccess: () => setDrawing(false), onError: () => setDrawing(false) })

  const lines = book.data?.lines ?? []
  const mbLines = lines.map(asMbLine)
  const byLine = new Map(lines.map((l) => [l.line_id, l]))
  const entries = book.data?.entries ?? []
  const filters = useListFilters(entries, {
    search: (e) => [e.fg_code, byLine.get(e.line_id ?? -1)?.description, e.location, e.mb_ref, e.remarks, e.recorded_by_name, e.witnessed_by, e.dimensions.map((d) => d.particulars).join(' ')].join(' '),
    date: (e) => e.measured_on,
  })
  const s = book.data?.summary

  const itemColumns: TableColumn<ClientBookLine>[] = [
    {
      id: 'item',
      header: 'Item',
      cell: (l) => (
        <div className="max-w-md">
          <span className="mr-2 font-mono text-xs font-semibold">{l.fg_code}</span>
          {l.description}
        </div>
      ),
    },
    { id: 'ordered', header: 'Ordered', align: 'right', cell: (l) => `${formatQty(l.ordered_qty)} ${l.uom}` },
    {
      id: 'measured',
      header: 'Measured',
      align: 'right',
      cell: (l) => (
        <div className="flex flex-col items-end">
          <span className={cn('font-medium', l.over_measured > 0 && 'text-danger')}>{formatQty(l.measured_to_date)}</span>
          <Progress percent={l.percent_measured} over={l.over_measured > 0} />
          {l.over_measured > 0 && <span className="mt-0.5 text-xs text-danger">{formatQty(l.over_measured)} over the order</span>}
        </div>
      ),
    },
    { id: 'left', header: 'Still to do', hideBelow: 'md', align: 'right', cell: (l) => formatQty(Math.max(0, l.balance_to_measure)) },
    { id: 'billed', header: 'Billed', hideBelow: 'lg', align: 'right', cell: (l) => formatQty(l.billed_to_date) },
    { id: 'unbilled', header: 'Unbilled', hideBelow: 'lg', align: 'right', cell: (l) => formatQty(l.unbilled) },
    { id: 'value', header: 'Unbilled value', hideBelow: 'xl', align: 'right', cell: (l) => formatINR(l.unbilled * l.rate) },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (l) =>
        record ? (
          <Button size="sm" onClick={() => setMeasuring(asMbLine(l))}>
            <Ruler /> Measure
          </Button>
        ) : null,
    },
  ]

  const entryColumns: TableColumn<ClientEntry>[] = [
    { id: 'date', header: 'Date', sort: (e) => e.measured_on, cell: (e) => formatDate(e.measured_on) },
    { id: 'item', header: 'Item', cell: (e) => <span className="font-mono text-xs">{e.fg_code}</span> },
    {
      id: 'dims',
      header: 'Particulars',
      hideBelow: 'lg',
      cell: (e) => {
        const parts = e.dimensions.filter((d) => !d.is_heading)
        return parts.length ? <span className="line-clamp-2 max-w-sm text-[13px] text-muted-foreground">{parts.map((d) => d.particulars || 'line').join(', ')}</span> : <span className="text-subtle">a total</span>
      },
    },
    { id: 'qty', header: 'Quantity', align: 'right', sort: (e) => e.quantity, cell: (e) => <span className={cn('font-medium', e.quantity < 0 && 'text-danger')}>{formatQty(e.quantity)}</span> },
    {
      id: 'ref',
      header: 'Ref',
      hideBelow: 'xl',
      cell: (e) => (
        <div>
          <span className="font-mono text-xs">{e.mb_ref || '-'}</span>
          {e.location && <div className="text-xs text-muted-foreground">{e.location}</div>}
        </div>
      ),
    },
    {
      id: 'who',
      header: 'Recorded by',
      hideBelow: 'xl',
      cell: (e) => (
        <div>
          {e.recorded_by_name}
          {e.witnessed_by && <div className="text-xs text-muted-foreground">witnessed: {e.witnessed_by}</div>}
        </div>
      ),
    },
    {
      id: 'del',
      header: '',
      align: 'right',
      cell: (e) =>
        e.billed ? (
          <Badge tone="info">Billed</Badge>
        ) : record ? (
          <Button variant="ghost" size="icon-sm" aria-label="Remove this entry" onClick={() => setRemoving(e)}>
            <Trash2 />
          </Button>
        ) : null,
    },
  ]

  const choose = (id: number) => {
    remember(id)
    setParams({ order: String(id) })
  }

  return (
    <>
      <PageHeader
        eyebrow="Clients"
        title="Measurement & RA Bills"
        description="What has actually been done on site, and the running account bills that follow from it."
        actions={
          can('billing.manage') && chosen > 0 ? (
            <Button onClick={() => setDrawing(true)} loading={draw.isPending}>
              Draw up a bill
            </Button>
          ) : undefined
        }
      />

      <div className="z-10 -mx-4 mb-6 border-b border-border bg-background/95 px-4 pb-3 pt-3 backdrop-blur sm:-mx-6 sm:px-6 md:sticky md:top-[calc(4rem+env(safe-area-inset-top))] lg:-mx-8 lg:px-8">
        <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,42rem)_minmax(0,1fr)]">
          <div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="sm:w-52 sm:shrink-0">
                <Select
                  aria-label="Site"
                  className="h-11"
                  value={site || ''}
                  placeholder={`All sites (${sites.length})`}
                  options={sites.map(([id, label]) => ({ value: id, label }))}
                  onChange={(e) => {
                    const id = Number(e.target.value) || 0
                    setSite(id)
                    const inSite = id ? listed.filter((o) => o.job_id === id) : listed
                    if (!inSite.some((o) => o.id === chosen) && inSite[0]) choose(inSite[0].id)
                  }}
                />
              </div>
              <div className="min-w-0 flex-1">
                <WorkOrderPicker orders={shown} selected={order} value={chosen} loading={orders.isPending} jobCode={jobCode} onChange={choose} />
              </div>
            </div>
            {order && (
              <p className="mt-1.5 truncate text-xs text-muted-foreground">
                {order.job_name} · {order.customer_name}
                {order.reference ? ` · ${order.reference}` : ''}
              </p>
            )}
          </div>
          {record && chosen > 0 && <QuickMeasure ref={quick} lines={mbLines} onPick={setMeasuring} />}
        </div>
      </div>

      {chosen === 0 && !orders.isPending && <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No approved client work orders yet. Place one under Client Work Orders, and once it is approved it can be measured here.</p>}

      {chosen > 0 && (
        <>
          <Statement workOrderId={chosen} />
          <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
            <Stat label="Ordered" value={compactINR(s?.ordered_value)} loading={book.isPending} />
            <Stat label="Measured" value={compactINR(s?.measured_value)} loading={book.isPending} />
            <Stat label="Measured, not billed" value={compactINR(s?.unbilled_value)} loading={book.isPending} />
            <Stat label="Lines over the order" value={s?.lines_over_measured ?? 0} tone={s?.lines_over_measured ? 'danger' : undefined} loading={book.isPending} />
          </StatGrid>

          <h2 className="mb-3 text-lg font-semibold">The measurement book</h2>
          <DataTable label="Items on the order" rows={lines} columns={itemColumns} rowKey={(l) => l.line_id} loading={book.isPending} empty="This order has no lines." className="mb-8" />

          <h2 className="mb-3 text-lg font-semibold">Entries</h2>
          <FilterBar filters={filters} placeholder="Search entries..." />
          <DataTable label="Measurement entries" rows={filters.filtered} columns={entryColumns} rowKey={(e) => e.id} loading={book.isPending} empty={filters.active ? 'Nothing matches those filters.' : 'Nothing measured yet.'} />

          <VariationsPanel workOrderId={chosen} />
          <BillsPanel workOrderId={chosen} />

          <MeasureModal
            orderId={chosen}
            order={order}
            jobCode={order ? jobCode(order) : ''}
            line={measuring}
            target={{ url: clientEntriesUrl(chosen), idKey: 'line_id', client: true, invalidate: refresh }}
            onClose={() => {
              setMeasuring(null)
              setTimeout(() => quick.current?.focus(), 0)
            }}
          />
          <ConfirmDialog
            open={!!removing}
            onOpenChange={(o) => !o && setRemoving(null)}
            title="Remove this measurement?"
            description="It comes out of the book. A measurement already billed cannot be removed."
            confirmLabel="Remove it"
            tone="danger"
            loading={remove.isPending}
            onConfirm={() => {
              if (removing) remove.mutate(removing)
            }}
          />
          <ConfirmDialog open={drawing} onOpenChange={setDrawing} title="Draw up a bill?" description="It claims what has been measured and not yet billed, less what earlier bills already took." confirmLabel="Draw it up" loading={draw.isPending} onConfirm={() => draw.mutate()} />
        </>
      )}
    </>
  )
}
