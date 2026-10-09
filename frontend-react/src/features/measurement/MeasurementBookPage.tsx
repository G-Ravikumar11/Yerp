import { useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { FileDown, FileUp, Lock, LockOpen, Receipt, Ruler, ScanText, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, ConfirmDialog, Select, Stat, StatGrid, Tabs } from '@/components/ui'
import { billKeys, drawBill } from '@/api/subbills'
import { deleteEntry, mbKeys, useMeasurementBook, type MbEntry, type MbLine } from '@/api/mb'
import { useOrderVocabulary, useOrders, type Order } from '@/api/orders'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { BulkBar, BulkDeleteDialog } from '@/components/data/BulkDelete'
import { HoldModal, ReleaseModal } from './HoldModals'
import { formatDate, formatQty } from '@/lib/format'
import { cn, compactINR, formatINR } from '@/lib/utils'
import { ImportBookModal } from './ImportBookModal'
import { BookAnalysis, ReadSheetModal } from './AiMeasurement'
import { SheetView } from './SheetView'
import { EntryDetail, calcSummary } from './EntryDetail'
import { MeasureModal } from './MeasureModal'
import { QuickMeasure, type QuickMeasureHandle } from './QuickMeasure'
import { WorkOrderPicker } from './WorkOrderPicker'

/** The work order the person was last measuring, so the book opens where they left off. */
const LAST = 'yerp.mb.order'
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
    // Private window: the book simply opens on the first order next time.
  }
}

/** A thin bar showing how much of an item is measured. Red past what was ordered. */
function Progress({ percent, over }: { percent: number; over: boolean }) {
  return (
    <div className="mt-1 h-1.5 w-28 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={Math.round(percent)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cn('h-full rounded-full transition-[width] duration-500', over ? 'bg-danger' : 'bg-primary')} style={{ width: `${Math.min(100, percent)}%` }} />
    </div>
  )
}

/** Why an order in the list cannot take a measurement. */
const WHY: Record<string, string> = {
  AMENDED: 'was amended. Its record is shown for reference and cannot take new measurements.',
  PROVISIONAL: 'is waiting for approval. It can be measured once it is approved.',
  DRAFT: 'is still a draft. It can be measured once it is submitted and approved.',
  CANCELLED: 'was cancelled. Nothing can be measured against it.',
}

export default function MeasurementBookPage() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const orders = useOrders()
  const all = orders.data?.orders ?? []
  const isLive = (o: Order) => o.status === 'APPROVED' || o.status === 'EXECUTED'
  // The book lists the orders that can be measured, and the amended ones whose record it holds.
  // Drafts, orders still waiting for approval and cancelled ones have nothing to measure, so they stay out.
  const order_of: Record<string, number> = { APPROVED: 0, EXECUTED: 0, AMENDED: 1 }
  // Each amended order sits directly under the revision that replaced it, so 002 is found beside 002-REV-02
  // rather than at the foot of the list. Amended orders with no revision in the book (an older order, or a
  // revision not yet approved) come last.
  const ranked = all.filter((o) => o.status in order_of)
  const placed = new Set<number>()
  const grouped: Order[] = []
  for (const o of ranked.filter(isLive)) {
    // The live order, then what it replaced, then what that replaced.
    for (let cur: Order | undefined = o; cur && !placed.has(cur.id); ) {
      placed.add(cur.id)
      grouped.push(cur)
      const before: number | null = cur.supersedes_id
      cur = before ? ranked.find((x) => x.id === before && x.status === 'AMENDED') : undefined
    }
  }
  const live = [...grouped, ...ranked.filter((o) => !placed.has(o.id))]
  // Work orders can be narrowed to one site (the project each is charged to).
  const [site, setSite] = useState(0)
  const sites = Array.from(new Map(live.filter((o) => o.job_id).map((o) => [o.job_id as number, o.project] as const)).entries()).sort((a, b) => a[1].localeCompare(b[1]))
  const shown = site ? live.filter((o) => o.job_id === site) : live
  const vocab = useOrderVocabulary()
  const jobCode = (o: Order) => vocab.data?.jobs.find((j) => j.id === o.job_id)?.number ?? ''
  // The order that carries on from an amended one: follow the revisions on to the one now live.
  const liveAfter = (from: Order | undefined) => {
    let cur = from
    for (let i = 0; i < 20 && cur?.status === 'AMENDED'; i++) cur = all.find((o) => o.supersedes_id === cur?.id && o.status in order_of)
    return cur && cur.id !== from?.id && isLive(cur) ? cur : undefined
  }
  // The book reopens on the order last worked on - and once that order has been amended and its revision
  // approved, on the revision, which is the one that takes measurements now.
  const lastOrder = all.find((o) => o.id === remembered())
  const last = (liveAfter(lastOrder) ?? lastOrder)?.id ?? 0
  const chosen = Number(params.get('order')) || (live.some((o) => o.id === last) ? last : 0) || live[0]?.id || 0
  const order = all.find((o) => o.id === chosen)
  const measurable = !!order && isLive(order)
  // The order that carries on from this one: follow the revisions on to the one now live.
  const replacement = liveAfter(order)
  const quick = useRef<QuickMeasureHandle>(null)
  const book = useMeasurementBook(chosen)
  const [measuring, setMeasuring] = useState<MbLine | null>(null)
  const [importing, setImporting] = useState(false)
  const [reading, setReading] = useState(false)
  const [holding, setHolding] = useState<MbLine | null>(null)
  const [picked, setPicked] = useState<Set<string | number>>(new Set())
  const [clearing, setClearing] = useState(false)
  const [releasing, setReleasing] = useState<MbEntry | null>(null)
  // The entries are listed as they always were; the Excel-style layout is one tab away. The choice is remembered.
  const [view, setViewState] = useState<'sheet' | 'list'>(() => {
    try {
      return localStorage.getItem('yerp.mb.view') === 'sheet' ? 'sheet' : 'list'
    } catch {
      return 'list'
    }
  })
  const [opened, setOpened] = useState<MbEntry | null>(null)
  const [changing, setChanging] = useState<MbEntry | null>(null)
  const setView = (v: 'sheet' | 'list') => {
    setViewState(v)
    try {
      localStorage.setItem('yerp.mb.view', v)
    } catch {
      // Private window: the choice lasts until the page closes.
    }
  }
  const [removing, setRemoving] = useState<MbEntry | null>(null)
  const record = can('site.record') && measurable
  // Billing staff and the owner hold work back; only the owner puts it back.
  const canHold = can('billing.manage') && measurable
  const { isOwner } = useSession()

  const nav = useNavigate()
  // Bill just the ticked entries: a bill drawn for them alone, the rest left for a later one.
  const billThese = useAction(() => drawBill(chosen, [...picked].map(Number)), {
    invalidate: [billKeys.all, mbKeys.all],
    onSuccess: (r) => {
      setPicked(new Set())
      nav(`/subcontractors/ra-bills/${r.bill.id}`)
    },
  })
  const remove = useAction((e: MbEntry) => deleteEntry(e.id), { invalidate: [mbKeys.all, ['subbills']], onSuccess: () => setRemoving(null), onError: () => setRemoving(null) })

  const lines = book.data?.lines ?? []
  const byItem = new Map(lines.map((l) => [l.item_id, l]))
  const entries = book.data?.entries ?? []
  const filters = useListFilters(entries, {
    search: (e) => [e.activity_no, byItem.get(e.item_id)?.item_code, byItem.get(e.item_id)?.description, e.location, e.mb_ref, e.remarks, e.recorded_by_name, e.dimensions.map((d) => d.particulars).join(' ')].join(' '),
    status: (e) => (e.billed ? 'Billed' : 'Not billed'),
    date: (e) => e.measured_on,
    facets: {
      item: { label: 'Items', get: (e) => [byItem.get(e.item_id)?.item_code, e.activity_no, byItem.get(e.item_id)?.description].filter(Boolean).join(' ').slice(0, 60) },
      who: { label: 'Recorded by', get: (e) => e.recorded_by_name },
      kind: { label: 'Kinds', get: (e) => (e.kind === 'hold' ? 'Holds' : e.kind === 'release' ? 'Releases' : 'Measured') },
    },
  })
  // Each item of the order: by code, activity or words, and by how far the work has got.
  const progress = (l: MbLine) => (l.is_header ? '' : l.over_measured ? 'Over measured' : !l.measured_to_date ? 'Not started' : (l.balance_to_measure ?? 0) <= 0 ? 'Complete' : 'In progress')
  const itemFilters = useListFilters(lines, {
    search: (l) => [l.item_code, l.activity_no, l.description, l.uom].join(' '),
    status: progress,
  })
  const s = book.data?.summary
  // Releases and holds go before the measurements they were held from, so a large clearing is never refused halfway.
  const kindOf = new Map(entries.map((e) => [e.id, e.kind ?? '']))
  const rank = (id: number) => ({ release: 0, hold: 1 } as Record<string, number>)[kindOf.get(id) ?? ''] ?? 2
  // Entries imported before holds were kept apart, still on a bill that has been sent (the rest were put right).
  const oldWay = entries.filter((e) => e.dimensions.some((d) => d.particulars.startsWith('Held back for finishes and handing over ('))).length

  const itemColumns: TableColumn<MbLine>[] = [
    { id: 'code', header: 'Item code', width: '7rem', cell: (l) => <span className="font-mono text-[13px] font-semibold">{l.is_header ? '' : l.item_code || '-'}</span> },
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
    { id: 'held', header: 'Held', align: 'right', hideBelow: 'lg', cell: (l) => (l.is_header ? '' : l.held ? <span className="font-medium text-warning">{formatQty(l.held)}</span> : '') },
    { id: 'left', header: 'Still to do', align: 'right', hideBelow: 'md', cell: (l) => (l.is_header ? '' : formatQty(Math.max(0, l.balance_to_measure ?? 0))) },
    { id: 'billed', header: 'Billed', align: 'right', hideBelow: 'lg', cell: (l) => (l.is_header ? '' : formatQty(l.billed_to_date)) },
    { id: 'unbilled', header: 'Unbilled', align: 'right', hideBelow: 'lg', cell: (l) => (l.is_header ? '' : formatQty(l.unbilled)) },
    { id: 'value', header: 'Unbilled value', align: 'right', hideBelow: 'xl', cell: (l) => (l.is_header ? '' : formatINR((l.unbilled ?? 0) * (l.rate ?? 0))) },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (l) =>
        !l.is_header && (record || canHold) ? (
          <div className="flex justify-end gap-1.5">
            {canHold && (
              <Button size="sm" variant="outline" onClick={() => setHolding(l)} disabled={(l.unbilled ?? 0) <= 0} title="Hold some of the measured work back from billing">
                <Lock /> Hold
              </Button>
            )}
            {record && (
              <Button size="sm" onClick={() => setMeasuring(l)}>
                <Ruler /> Measure
              </Button>
            )}
          </div>
        ) : null,
    },
  ]

  const entryColumns: TableColumn<MbEntry>[] = [
    { id: 'code', header: 'Entry', sort: (e) => e.code ?? '', cell: (e) => <span className="whitespace-nowrap font-mono text-xs font-medium">{e.code ? e.code.slice(e.code.lastIndexOf('/') + 1) : '-'}</span> },
    { id: 'date', header: 'Date', sort: (e) => e.measured_on, cell: (e) => formatDate(e.measured_on) },
    {
      id: 'item',
      header: 'Activity',
      cell: (e) => (
        <div className="max-w-xs">
          <div className="truncate">
            {byItem.get(e.item_id)?.item_code && <span className="mr-1.5 font-mono text-xs font-semibold">{byItem.get(e.item_id)?.item_code}</span>}
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
    { id: 'calc', header: 'Calculation', hideBelow: 'xl', cell: (e) => <span className="line-clamp-2 max-w-xs font-mono text-xs text-muted-foreground">{calcSummary(e) || '-'}</span> },
    { id: 'qty', header: 'Quantity', align: 'right', sort: (e) => e.quantity, cell: (e) => <span className={cn('font-medium', e.quantity < 0 && 'text-danger')}>{formatQty(e.quantity)}</span> },
    { id: 'ref', header: 'Ref', hideBelow: 'xl', cell: (e) => <span className="font-mono text-xs">{e.mb_ref || '-'}</span> },
    { id: 'who', header: 'Recorded by', hideBelow: 'xl', cell: (e) => e.recorded_by_name },
    {
      id: 'billed',
      header: '',
      cell: (e) =>
        e.kind === 'hold' ? (
          <Badge tone={(e.held_remaining ?? 0) > 0 ? 'warning' : 'neutral'}>{(e.held_remaining ?? 0) > 0 ? 'Held' : 'Released'}</Badge>
        ) : e.kind === 'release' ? (
          <Badge tone="success">Released</Badge>
        ) : e.billed ? (
          <Badge tone="info">Billed</Badge>
        ) : null,
    },
    {
      id: 'del',
      header: '',
      align: 'right',
      width: '3rem',
      cell: (e) => (
        <div className="flex justify-end gap-1">
          {e.kind === 'hold' && (e.held_remaining ?? 0) > 0 && isOwner && (
            <Button variant="ghost" size="icon-sm" aria-label="Release this hold" title="Release this hold" onClick={(ev) => { ev.stopPropagation(); setReleasing(e) }}>
              <LockOpen />
            </Button>
          )}
          {record && !e.billed ? (
          <Button variant="ghost" size="icon-sm" aria-label="Remove this entry" onClick={(ev) => { ev.stopPropagation(); setRemoving(e) }}>
            <Trash2 />
          </Button>
          ) : null}
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Subcontractors"
        title="Measurement Book"
        description={`What the contractor has built, measured line by line. Only measured work can be billed, and nothing is billed twice.${order ? ` Book no. ${order.wo_number}/MB - each entry has its own number in it.` : ''}`}
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
            {record && chosen > 0 && (
              <Button variant="outline" onClick={() => setReading(true)}>
                <ScanText /> Read a sheet
              </Button>
            )}
          </>
        }
      />

      <div className="z-10 md:sticky md:top-[calc(4rem+env(safe-area-inset-top))] -mx-4 mb-6 border-b border-border bg-background/95 px-4 pb-3 pt-3 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
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
                    // Moving to a site whose list does not hold the open order opens that site's first one.
                    const inSite = id ? live.filter((o) => o.job_id === id) : live
                    if (!inSite.some((o) => o.id === chosen)) {
                      const next = inSite.find(isLive) ?? inSite[0]
                      if (next) {
                        remember(next.id)
                        setParams({ order: String(next.id) })
                      }
                    }
                  }}
                />
              </div>
              <div className="min-w-0 flex-1">
                <WorkOrderPicker
                  orders={shown}
                  selected={order}
                  value={chosen}
                  loading={orders.isPending}
                  jobCode={jobCode}
                  onChange={(id) => {
                    remember(id)
                    setParams({ order: String(id) })
                  }}
                />
              </div>
            </div>
            {order && (
              <p className="mt-1.5 truncate text-xs text-muted-foreground" title={`${order.project} · ${order.subject}`}>
                {order.project}
                {order.subject ? ` · ${order.subject}` : ''}
              </p>
            )}
          </div>
          {record && chosen > 0 && <QuickMeasure ref={quick} lines={lines} onPick={setMeasuring} />}
        </div>
      </div>

      {order && !measurable && (
        <div role="status" className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm">
          <p>
            <span className="font-mono font-semibold">{order.wo_number}</span>{' '}
            {replacement ? (
              <>
                was amended and replaced by <span className="font-mono font-semibold">{replacement.wo_number}</span>. Measure against the revision; what was measured and billed here carried across to it.
              </>
            ) : (
              (WHY[order.status] ?? `is ${order.status.toLowerCase()} and cannot be measured.`)
            )}
          </p>
          {replacement && (
            <Button
              size="sm"
              onClick={() => {
                remember(replacement.id)
                setParams({ order: String(replacement.id) })
              }}
            >
              Open {replacement.wo_number}
            </Button>
          )}
        </div>
      )}

      {chosen > 0 && (
        <>
          <StatGrid className="lg:grid-cols-5 xl:grid-cols-5">
            <Stat label="Order value" value={compactINR(s?.ordered_value)} loading={book.isPending} />
            <Stat label="Work measured" value={compactINR(s?.measured_value)} loading={book.isPending} />
            <Stat label="Measured, not billed" value={compactINR(s?.unbilled_value)} loading={book.isPending} />
            <Stat label="Held back" value={compactINR(s?.held_value)} tone={s?.held_value ? 'warning' : undefined} loading={book.isPending} />
            <Stat label="Items over the order" value={s?.lines_over_measured ?? 0} tone={s?.lines_over_measured ? 'danger' : undefined} loading={book.isPending} />
          </StatGrid>

          <BookAnalysis key={chosen} orderId={chosen} />

          <h2 className="mb-3 text-lg font-semibold">Items on the order - measure each one</h2>
          <FilterBar filters={itemFilters} placeholder="Search by item code, activity or words..." />
          <DataTable label="Items on the order" rows={itemFilters.filtered} columns={itemColumns} rowKey={(l) => l.item_id} loading={book.isPending} empty={itemFilters.active ? 'No item matches those filters.' : 'This order has no schedule lines.'} className="mb-8" />

          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Measurement entries</h2>
            <Tabs label="How to show the entries" value={view} onChange={setView} items={[{ value: 'list', label: 'Entries' }, { value: 'sheet', label: 'Excel layout' }]} />
          </div>
          {(book.data?.entries_total ?? 0) > entries.length && (
            <p role="alert" className="mb-3 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-[13px]">
              Showing the newest {entries.length} of {book.data?.entries_total} entries. Everything is still counted in the totals and the bill.
            </p>
          )}
          {oldWay > 0 && (
            <p role="note" className="mb-3 rounded-lg border border-border bg-muted/40 px-3 py-2 text-[13px] text-muted-foreground">
              {oldWay} {oldWay === 1 ? 'entry was' : 'entries were'} imported before holds were kept apart and {oldWay === 1 ? 'is' : 'are'} on a bill already sent, so {oldWay === 1 ? 'it keeps' : 'they keep'} the hold as a line inside the block. To have the blocks match the sheet, delete that bill and import again.
            </p>
          )}
          <FilterBar filters={filters} placeholder="Search entries..." />
          {record && view === 'list' && <BulkBar count={picked.size} noun="entry" shown={filters.filtered.filter((e) => !e.billed).length} onClear={() => setPicked(new Set())} onDelete={() => setClearing(true)} actions={can('billing.manage') && measurable ? <Button size="sm" loading={billThese.isPending} onClick={() => billThese.mutate()}><Receipt /> Bill {picked.size}</Button> : undefined} />}
          {view === 'sheet' ? <SheetView entries={filters.filtered} byItem={byItem} /> : <DataTable
            label="Measurement entries"
            rows={filters.filtered}
            columns={entryColumns}
            selection={record ? { selected: picked, onChange: setPicked, canSelect: (e) => !e.billed } : undefined}
            onRowClick={setOpened}
            rowKey={(e) => e.id}
            loading={book.isPending}
            empty={filters.active ? 'Nothing matches those filters.' : 'Nothing measured yet.'}
          />}

          <EntryDetail
            entry={opened}
            line={opened ? byItem.get(opened.item_id) : undefined}
            canChange={record && !opened?.billed && !opened?.kind}
            onClose={() => setOpened(null)}
            onEdit={(e) => {
              setOpened(null)
              setChanging(e)
            }}
            onRemove={(e) => {
              setOpened(null)
              setRemoving(e)
            }}
          />
          <MeasureModal
            orderId={chosen}
            order={order}
            jobCode={order ? jobCode(order) : ''}
            line={changing ? byItem.get(changing.item_id) ?? null : null}
            entry={changing}
            onClose={() => setChanging(null)}
          />
          <MeasureModal
            orderId={chosen}
            order={order}
            jobCode={order ? jobCode(order) : ''}
            line={measuring}
            onClose={() => {
              setMeasuring(null)
              // Straight back to the code box for the next item.
              setTimeout(() => quick.current?.focus(), 0)
            }}
          />
          <ImportBookModal orderId={chosen} open={importing} onOpenChange={setImporting} />
          <ReadSheetModal orderId={chosen} lines={lines} open={reading} onClose={() => setReading(false)} />
          <BulkDeleteDialog open={clearing} onOpenChange={setClearing} kind="entry" noun="entry" ids={[...picked].map(Number).sort((a, b) => rank(a) - rank(b))} onFinished={() => setPicked(new Set())} detail="Each measurement is taken out of the book and off any draft bill it was on. Measurements on a sent bill stay. This cannot be undone." />
          <HoldModal orderId={chosen} line={holding} onClose={() => setHolding(null)} />
          <ReleaseModal entry={releasing} line={releasing ? byItem.get(releasing.item_id) : undefined} onClose={() => setReleasing(null)} />
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
