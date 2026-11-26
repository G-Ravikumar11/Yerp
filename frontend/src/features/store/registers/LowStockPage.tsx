import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ShoppingCart, TriangleAlert } from 'lucide-react'
import { Badge, Button, Card } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { cn } from '@/lib/utils'
import { dmy } from '../reports/api'
import { matching, useLowHistory, useLowStock, type LowHistoryRow, type LowRow, type LowStage, type LowStatus } from './api'
import { RaiseLowStock } from './RaiseLowStock'
import { RegisterFilters, RegisterHeader } from './RegisterParts'

const n = (v: string | number | null) => Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })
const STATUS: Record<LowStatus | 'RESOLVED', { label: string; tone: 'danger' | 'info' | 'warning' | 'success' }> = {
  LOW_STOCK: { label: 'LOW STOCK', tone: 'danger' },
  INDENT_RAISED: { label: 'INDENT RAISED', tone: 'info' },
  ENQUIRY_RAISED: { label: 'ENQUIRY RAISED', tone: 'warning' },
  RESOLVED: { label: 'RESOLVED', tone: 'success' },
}
/** The alert's way to replenishment: raised, ordered, received, passed QC, posted - and back to low if still under its level. */
const STAGE: Record<LowStage, 'danger' | 'info' | 'warning' | 'success' | 'neutral'> = {
  'ALERT ACTIVE': 'danger', 'INDENT RAISED': 'info', 'ENQUIRY RAISED': 'warning', 'PO CREATED': 'info',
  'GOODS RECEIVED': 'warning', 'QUALITY ACCEPTED': 'success', 'STOCK UPDATED': 'success', 'LOW STOCK': 'danger',
}

/** Store > Low Stock: what is low now - its available stock (not just what is on hand) at or under its reorder level - worst first, with how
 * much to order, the alert's dates and the indent or enquiry raised for it. Tick the ones to act on and raise them together.
 * `storeId` given: it sits in the Store Desk, which chooses the store and has the heading. */
export function LowStockList({ storeId: fixed }: { storeId?: number } = {}) {
  const embedded = fixed !== undefined
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [own, setStoreId] = useState(0)
  const [view, setView] = useState<'active' | 'history'>('active')
  const [picked, setPicked] = useState<ReadonlySet<string | number>>(new Set())
  const [raising, setRaising] = useState(false)
  const storeId = fixed ?? own
  const stock = useLowStock(storeId)
  const history = useLowHistory(storeId, view === 'history')
  const fromDesk = embedded ? '&from=desk' : ''
  const all = useMemo(() => stock.data?.items ?? [], [stock.data])
  const rows = matching(all, q, (r) => [r.item_name, r.item_code, r.category, r.store_name, r.store_code, r.project])
  const chosen = all.filter((r) => picked.has(r.key))
  const canRaise = !!stock.data && (stock.data.can_indent || stock.data.can_enquire)
  const old = matching(history.data ?? [], q, (r) => [r.item_name, r.item_code, r.store_code, r.action_ref])

  const columns: TableColumn<LowRow>[] = [
    { id: 'name', header: 'Material', sort: (r) => r.item_name, cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'loc', header: 'Store', width: '9rem', hideBelow: 'sm', sort: (r) => r.store_code, cell: (r) => <div>{r.store_code}<div className="text-xs text-muted-foreground">{r.project || r.store_name}</div></div> },
    {
      id: 'avail', header: 'Available', align: 'right', width: '8rem', sort: (r) => Number(r.available),
      cell: (r) => (
        <div><span className="font-semibold text-danger">{n(r.available)}</span> <span className="text-xs text-muted-foreground">{r.base_uom}</span>
          {Number(r.on_hand) !== Number(r.available) && <div className="text-[11px] font-normal text-muted-foreground" title="In the store now, before taking out what is held, rejected, expired or kept for approved requests">{n(r.on_hand)} on hand</div>}</div>
      ),
    },
    { id: 'lvl', header: 'Reorder level', align: 'right', width: '7rem', hideBelow: 'md', sort: (r) => Number(r.reorder_level), cell: (r) => <div>{n(r.reorder_level)}{Number(r.shortage) > 0 && <div className="text-[11px] text-danger">{n(r.shortage)} short</div>}</div> },
    {
      id: 'sug', header: 'Suggested reorder', align: 'right', width: '8rem', sort: (r) => Number(r.suggested_qty),
      cell: (r) => <div title={r.suggest_basis}>{n(r.suggested_qty)} <span className="text-xs text-muted-foreground">{r.base_uom}</span>{Number(r.on_order) > 0 && <div className="text-[11px] text-muted-foreground">{n(r.on_order)} already coming</div>}</div>,
    },
    { id: 'since', header: 'Alert raised', width: '8rem', hideBelow: 'lg', sort: (r) => r.alerted_at, cell: (r) => (r.alerted_at ? <div className="text-xs"><div>{dmy(r.alerted_at)}</div><div className="text-muted-foreground">checked {dmy(r.last_checked_at)}</div></div> : '-') },
    {
      id: 'status', header: 'Status', width: '11rem', sort: (r) => r.status,
      cell: (r) => (
        <div>
          <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>
          {r.stage && r.stage !== STATUS[r.status].label && <Badge tone={STAGE[r.stage] ?? 'neutral'} className="ml-1" title="How far replenishment has got">{r.stage}</Badge>}
          {r.action && (
            <div className="mt-0.5 text-xs text-muted-foreground" title={r.action_by ? `Raised by ${r.action_by}` : undefined}>
              {r.action === 'INDENT' ? 'Material request' : 'Enquiry'} {r.action_ref}{r.action_doc_status ? ` - ${r.action_doc_status.toLowerCase()}` : ''}{r.action_qty ? ` for ${n(r.action_qty)}` : ''}
              {!r.action_live && <span className="block text-warning">no longer open - still low</span>}
            </div>
          )}
        </div>
      ),
    },
  ]
  const old_columns: TableColumn<LowHistoryRow>[] = [
    { id: 'name', header: 'Material', cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'store', header: 'Store', width: '6rem', cell: (r) => r.store_code },
    { id: 'raised', header: 'Alert raised', width: '8rem', cell: (r) => (r.alerted_at ? dmy(r.alerted_at) : '-') },
    { id: 'low', header: 'Available then', align: 'right', width: '8rem', cell: (r) => `${n(r.available)} / ${n(r.reorder_level)}` },
    { id: 'res', header: 'Resolved', width: '9rem', cell: (r) => <div><Badge tone="success">RESOLVED</Badge><div className="mt-0.5 text-xs text-muted-foreground">{r.resolved_at ? dmy(r.resolved_at) : ''}{r.resolved_qty ? ` at ${n(r.resolved_qty)}` : ''}</div></div> },
    { id: 'act', header: 'Raised for it', cell: (r) => (r.action ? <span className="text-xs">{r.action === 'INDENT' ? 'Material request' : 'Enquiry'} {r.action_ref}{r.action_qty ? ` for ${n(r.action_qty)}` : ''}{r.action_by ? ` by ${r.action_by}` : ''}</span> : <span className="text-xs text-muted-foreground">Nothing raised</span>) },
  ]
  return (
    <div>
      <RegisterHeader embedded={embedded} title="Low Stock Alerts" description="Materials whose available stock is at or below the reorder level."
        actions={<Button variant="outline" asChild><Link to="/store/hub/reports/reorder">Reorder report</Link></Button>} />
      {view === 'active' && all.length > 0 && (
        <div role="status" className="mb-5 flex items-center gap-2.5 rounded-xl border border-warning/40 bg-warning-soft px-4 py-3 text-sm text-warning">
          <TriangleAlert className="size-5 shrink-0" />
          {all.length} {all.length === 1 ? 'material is' : 'materials are'} at or below the reorder level. Tick them and raise an indent or enquiry together.
        </div>
      )}
      <Card className="p-4">
        <RegisterFilters q={q} onQ={setQ} storeId={storeId} onStore={embedded ? undefined : setStoreId} />
        <div role="group" aria-label="Alerts shown" className="mb-3 flex flex-wrap items-center gap-1.5">
          {([['active', `Low now (${all.length})`], ['history', 'Resolved alerts']] as const).map(([v, label]) => (
            <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
              className={cn('rounded-md border px-3 py-1.5 text-[13px] font-medium transition-colors', view === v ? 'border-primary bg-primary-soft text-primary' : 'border-border bg-card text-muted-foreground hover:text-foreground')}>{label}</button>
          ))}
          {view === 'active' && canRaise && (
            <div className="ml-auto flex items-center gap-3">
              <span className="text-sm text-muted-foreground" aria-live="polite">{picked.size} selected</span>
              {picked.size > 0 && <Button size="sm" variant="ghost" onClick={() => setPicked(new Set())}>Clear</Button>}
              <Button size="sm" disabled={!chosen.length} onClick={() => setRaising(true)}><ShoppingCart /> Ask to buy all selected</Button>
            </div>
          )}
        </div>
        {view === 'active' ? (
          stock.isError ? <p role="alert" className="text-sm text-danger">Could not load the low stock.</p> : (
            <DataTable label="Low stock" rows={rows} loading={stock.isPending} columns={columns} rowKey={(r) => r.key}
              selection={canRaise ? { selected: picked, onChange: setPicked } : undefined}
              onRowClick={(r) => nav(`/store/hub/enquiry/card?store=${r.store_id}&item=${r.item_id}${fromDesk}`)}
              empty="Nothing is low. An item shows here when what is available of it falls to its reorder level, set on the item or the store." />
          )
        ) : history.isError ? <p role="alert" className="text-sm text-danger">Could not load the resolved alerts.</p> : (
          <DataTable label="Resolved low stock alerts" rows={old} loading={history.isPending} columns={old_columns} rowKey={(r) => `${r.alert_id}-${r.alerted_at}-${r.resolved_at}`}
            empty="No alert has been resolved yet. One is resolved when the stock is back above the reorder level; it is kept here." />
        )}
      </Card>
      {raising && stock.data && chosen.length > 0 && (
        <RaiseLowStock rows={chosen} canIndent={stock.data.can_indent} canEnquire={stock.data.can_enquire} onClose={() => { setRaising(false); setPicked(new Set()) }} />
      )}
    </div>
  )
}

export default function LowStockPage() {
  return <LowStockList />
}
