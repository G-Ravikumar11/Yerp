import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight } from 'lucide-react'
import { Badge, Card, Skeleton, Stat } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { get } from '@/lib/api'
import { formatDate, formatQty } from '@/lib/format'
import { formatINR } from '@/lib/utils'

/** Amounts and quantities travel as decimal strings; they are only ever shown here, never added up. */
type Num = string

interface LowRow { store_id: number; store_code: string; item_id: number; item_code: string; item_name: string; base_uom: string; qty: Num; reorder_level: Num; suggested_qty: Num }
interface Waiting { label: string; action: string; count: number; path: string }
interface Movement { id: number; date: string; store_code: string; item_id: number; item_code: string; item_name: string; movement_type: string; qty: Num; value: Num; reversal: boolean; doc_number: string; doc_path: string }
interface BudgetRow { project_id: number; project: string; allocated: Num; committed: Num; store_material: Num; left: Num; over: boolean; used_pct: number | null }
export interface StoreDashboard {
  as_on: string
  waiting: Waiting[]
  stock: { stores: number; items_in_stock: number; lines_in_stock: number; total_value: Num; low_stock: number; out_of_stock: number; low_rows: LowRow[] } | null
  recent: Movement[] | null
  overdue_returnables: number | null
  budgets: { rows: BudgetRow[]; projects: number; over: number; totals: Record<'allocated' | 'committed' | 'store_material' | 'left', Num> } | null
}

/** Asked afresh whenever the Overview is opened, so it shows what the documents just saved did - it is cheap and read only. */
export const useStoreDashboard = (enabled = true) => useQuery({ queryKey: ['store', 'dashboard'], queryFn: () => get<StoreDashboard>('/api/store/dashboard'), staleTime: 0, refetchOnMount: 'always', enabled })

const inr = (x: Num) => formatINR(Number(x))
const qty = (x: Num) => formatQty(Number(x))
const head = 'mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground'

/** The figures across the top of the Store front page, each opening the screen it comes from. */
export function OverviewStats({ d }: { d?: StoreDashboard }) {
  if (!d) return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}</div>
  const s = d.stock
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {s && <Stat label="Stock value" value={inr(s.total_value)} sub={`${s.items_in_stock} item${s.items_in_stock === 1 ? '' : 's'} held in ${s.stores} store${s.stores === 1 ? '' : 's'}`} to="/store/hub/reports/valuation" />}
      {s && <Stat label="Low stock" value={s.low_stock} tone={s.low_stock ? 'warning' : undefined} sub="At or below the reorder level" to="/store/hub/reports/reorder" />}
      {s && <Stat label="Out of stock" value={s.out_of_stock} tone={s.out_of_stock ? 'danger' : undefined} sub="Nothing left of an item that has a reorder level" to="/store/hub/reports/reorder" />}
      {d.overdue_returnables !== null && <Stat label="Returnables overdue" value={d.overdue_returnables} tone={d.overdue_returnables ? 'warning' : undefined} sub="Tools and items not back by their date" to="/store/hub/outward/returnables" />}
    </div>
  )
}

/** Documents waiting on this person - only those they may approve, post or receive - and the items running out. */
export function OverviewWork({ d }: { d?: StoreDashboard }) {
  if (!d) return null
  const low = d.stock?.low_rows ?? []
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section>
        <h2 className={head}>Waiting on you</h2>
        <Card className="divide-y divide-border">
          {d.waiting.length === 0 && <p className="p-4 text-sm text-muted-foreground">Nothing is waiting for you to approve, post or receive.</p>}
          {d.waiting.map((w) => (
            <Link key={w.label + w.action} to={w.path} className="flex items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-accent">
              <span><span className="font-semibold">{w.count}</span> {w.label.toLowerCase()} {w.action}</span>
              <ArrowRight className="size-4 text-muted-foreground" />
            </Link>
          ))}
        </Card>
      </section>
      {d.stock && (
        <section>
          <h2 className={head}>Running out</h2>
          <Card className="divide-y divide-border">
            {low.length === 0 && <p className="p-4 text-sm text-muted-foreground">No item is at or below its reorder level.</p>}
            {low.map((r) => (
              <Link key={`${r.store_id}-${r.item_id}`} to={`/store/hub/enquiry/card?item=${r.item_id}`} className="flex items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-accent">
                <span className="min-w-0"><span className="font-medium">{r.item_name}</span> <span className="font-mono text-xs text-muted-foreground">{r.store_code}</span></span>
                <span className={Number(r.qty) <= 0 ? 'shrink-0 font-medium text-danger' : 'shrink-0 text-warning'}>{Number(r.qty) <= 0 ? 'None left' : `${qty(r.qty)} ${r.base_uom}`} <span className="text-xs text-muted-foreground">/ reorder at {qty(r.reorder_level)}</span></span>
              </Link>
            ))}
            {d.stock.low_stock > low.length && <Link to="/store/hub/reports/reorder" className="block px-4 py-3 text-sm text-primary hover:bg-accent">All {d.stock.low_stock} in the reorder report</Link>}
          </Card>
        </section>
      )}
    </div>
  )
}

const TYPE: Record<string, string> = {
  OPENING_IN: 'Opening', GRN_IN: 'Received', CLIENT_SUPPLY_IN: 'Client supply', PURCHASE_RETURN_OUT: 'Returned to supplier', ISSUE_OUT: 'Issued',
  ISSUE_RETURN_IN: 'Returned from site', SUBCON_ISSUE_OUT: 'Issued to subcontractor', SUBCON_RETURN_IN: 'Back from subcontractor', TRANSFER_OUT: 'Sent',
  TRANSFER_IN: 'Arrived', ADJUST_IN: 'Count gain', ADJUST_OUT: 'Count loss', WASTAGE_OUT: 'Wastage', SCRAP_OUT: 'Scrap',
}

/** The last stock movements in this person's stores, each opening the document that made it. */
export function OverviewMovements({ d }: { d?: StoreDashboard }) {
  if (!d || d.recent === null) return null
  const columns: TableColumn<Movement>[] = [
    { id: 'date', header: 'Date', width: '7rem', cell: (m) => formatDate(m.date) },
    { id: 'item', header: 'Item', cell: (m) => <Link className="hover:underline" to={`/store/hub/enquiry/card?item=${m.item_id}`}><span className="font-medium">{m.item_name}</span> <span className="font-mono text-xs text-muted-foreground">{m.item_code}</span></Link> },
    { id: 'what', header: 'Movement', width: '11rem', hideBelow: 'sm', cell: (m) => <span>{TYPE[m.movement_type] ?? m.movement_type}{m.reversal && <Badge className="ml-1.5" tone="warning">Reversed</Badge>}</span> },
    { id: 'qty', header: 'Qty', align: 'right', width: '6rem', cell: (m) => <span className={Number(m.qty) < 0 ? 'text-danger' : 'text-success'}>{Number(m.qty) > 0 ? '+' : ''}{qty(m.qty)}</span> },
    { id: 'val', header: 'Value', align: 'right', width: '8rem', hideBelow: 'md', cell: (m) => inr(m.value) },
    { id: 'store', header: 'Store', width: '5rem', hideBelow: 'lg', cell: (m) => <span className="font-mono text-[13px]">{m.store_code}</span> },
    { id: 'doc', header: 'Document', width: '10rem', hideBelow: 'md', cell: (m) => (m.doc_path ? <Link className="font-mono text-[13px] text-primary hover:underline" to={m.doc_path}>{m.doc_number || 'Open'}</Link> : '-') },
  ]
  return (
    <section>
      <div className="mb-3 flex items-center justify-between"><h2 className={head + ' mb-0'}>Latest movements</h2><Link to="/store/hub/enquiry" className="text-sm text-primary hover:underline">Stock enquiry</Link></div>
      <DataTable label="Latest stock movements" rows={d.recent} columns={columns} rowKey={(m) => m.id} empty="No stock has moved yet." />
    </section>
  )
}

/** Each project's budget beside what is spent of it: work orders committed and material the store has issued. Shown, never enforced. */
export function OverviewBudgets({ d }: { d?: StoreDashboard }) {
  if (!d || d.budgets === null) return null
  const b = d.budgets
  const columns: TableColumn<BudgetRow>[] = [
    { id: 'p', header: 'Project', cell: (r) => <Link className="font-medium hover:underline" to={`/projects/${r.project_id}`}>{r.project}</Link> },
    { id: 'a', header: 'Allocated', align: 'right', width: '8rem', cell: (r) => (Number(r.allocated) ? inr(r.allocated) : <span className="text-muted-foreground">Not set</span>) },
    { id: 'c', header: 'Work orders', align: 'right', width: '8rem', hideBelow: 'md', cell: (r) => inr(r.committed) },
    { id: 'm', header: 'Store material', align: 'right', width: '8rem', cell: (r) => inr(r.store_material) },
    { id: 'l', header: 'Left', align: 'right', width: '9rem', cell: (r) => (Number(r.allocated) ? <span className={r.over ? 'font-medium text-danger' : ''}>{inr(r.left)}{r.used_pct !== null && <span className="ml-1 text-xs text-muted-foreground">({r.used_pct}% used)</span>}</span> : '-') },
  ]
  return (
    <section>
      <h2 className={head}>Project budgets</h2>
      <p className="mb-3 text-sm text-muted-foreground">
        What each project is allocated, what its work orders have committed and what the store has issued to it at cost. This is for information: an issue to site is never stopped for it.
        {b.over > 0 && <span className="ml-1 inline-flex items-center gap-1 text-danger"><AlertTriangle className="size-3.5" />{b.over} project{b.over === 1 ? ' is' : 's are'} over.</span>}
      </p>
      <DataTable label="Project budgets" rows={b.rows} columns={columns} rowKey={(r) => r.project_id} empty="No project has a budget or store material yet." />
      {b.projects > b.rows.length && <p className="mt-2 text-xs text-muted-foreground">Showing the {b.rows.length} most used of {b.projects} projects.</p>}
    </section>
  )
}
