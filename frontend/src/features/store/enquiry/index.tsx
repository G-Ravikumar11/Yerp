import { useEffect, useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, FileText, Search, Undo2 } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Card, Field, Input, Select, Stat, StatGrid, Tabs } from '@/components/ui'
import { formatDate } from '@/lib/format'
import { cn, formatINR } from '@/lib/utils'
import { StoreShell } from '../StoreShell'
import { ItemPicker, StorePicker } from '../shared'
import {
  cardPath, useAvailability, useBalances, useItemCard, type BalanceFilter, type CardRow, type Group, type GroupedBalance, type StoreBalance,
} from './api'

const BASE = '/store/hub/enquiry'
const money = (s: string | undefined) => formatINR(Number(s ?? 0))
const qty = (s: string, uom: string) => `${Number(s).toLocaleString('en-IN', { maximumFractionDigits: 3 })} ${uom}`

/** Store > Stock enquiry. Sub-pages live under /store/hub/enquiry/*. */
export default function EnquiryIndex() {
  return (
    <StoreShell slice="enquiry">
      <Routes>
        <Route index element={<BalancesPage />} />
        <Route path="items/:itemId" element={<ItemCardPage />} />
        <Route path="items/:itemId/where" element={<AvailabilityPage />} />
        <Route path="*" element={<p className="text-sm text-muted-foreground">There is no such page in Stock enquiry.</p>} />
      </Routes>
    </StoreShell>
  )
}

const GROUPS: { value: Group; label: string; info: string }[] = [
  { value: 'store', label: 'By store', info: 'One line for each item in each store.' },
  { value: 'item', label: 'By item', info: 'Each item added up across the stores you work in.' },
  { value: 'project', label: 'By project', info: 'Each item added up across the stores of each project; the central store and yards show as "Not on a project".' },
]

function BalancesPage() {
  const nav = useNavigate()
  const [text, setText] = useState('')
  const [f, setF] = useState<BalanceFilter>({ group: 'store', storeId: 0, projectId: 0, q: '', category: '', includeZero: false })
  useEffect(() => {
    const t = setTimeout(() => setF((x) => ({ ...x, q: text.trim() })), 250)
    return () => clearTimeout(t)
  }, [text])
  const b = useBalances(f)
  const s = b.data?.summary
  const itemCell = (r: { item_code: string; item_name: string; category: string | null }) => (
    <div><span className="font-mono text-xs text-muted-foreground max-sm:hidden">{r.item_code} </span>{r.item_name}{r.category && r.category !== 'CONSUMABLE' && <Badge className="ml-2">{r.category.toLowerCase()}</Badge>}</div>
  )
  const byStore: TableColumn<StoreBalance>[] = [
    { id: 'store', header: 'Store', width: '6.5rem', sort: (r) => r.store_code, cell: (r) => <div><span className="font-mono font-semibold">{r.store_code}</span>{r.project && <div className="truncate text-xs text-muted-foreground">{r.project}</div>}</div> },
    { id: 'item', header: 'Item', sort: (r) => r.item_name, cell: itemCell },
    { id: 'qty', header: 'On hand', align: 'right', sort: (r) => Number(r.qty), cell: (r) => <div className={cn('font-semibold', r.below_reorder && 'text-warning')}>{qty(r.qty, r.base_uom)}{r.below_reorder && <div className="text-[11px] font-normal">below {Number(r.reorder_level)}</div>}</div> },
    { id: 'rate', header: 'Avg rate', align: 'right', hideBelow: 'md', cell: (r) => formatINR(Number(r.avg_rate)) },
    { id: 'value', header: 'Value', align: 'right', sort: (r) => Number(r.value), cell: (r) => <strong>{money(r.value)}</strong> },
  ]
  const grouped: TableColumn<GroupedBalance>[] = [
    ...(f.group === 'project' ? [{ id: 'project', header: 'Project', sort: (r: GroupedBalance) => r.project ?? '', cell: (r: GroupedBalance) => r.project }] : []),
    { id: 'item', header: 'Item', sort: (r) => r.item_name, cell: itemCell },
    { id: 'stores', header: 'Held at', hideBelow: 'md', cell: (r) => r.stores.join(', ') },
    { id: 'qty', header: 'On hand', align: 'right', sort: (r) => Number(r.qty), cell: (r) => <span className="font-semibold">{qty(r.qty, r.base_uom)}</span> },
    { id: 'rate', header: 'Avg rate', align: 'right', hideBelow: 'md', cell: (r) => formatINR(Number(r.avg_rate)) },
    { id: 'value', header: 'Value', align: 'right', sort: (r) => Number(r.value), cell: (r) => <strong>{money(r.value)}</strong> },
  ]
  return (
    <div>
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Value held" value={money(s?.total_value)} loading={b.isPending} />
        <Stat label="Items" value={s?.items ?? 0} loading={b.isPending} />
        <Stat label="Stores" value={s?.stores ?? 0} loading={b.isPending} />
        <Stat label="Below reorder level" value={s?.below_reorder ?? 0} tone={s?.below_reorder ? 'warning' : undefined} loading={b.isPending} />
      </StatGrid>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tabs label="Group by" value={f.group} onChange={(group) => setF({ ...f, group })} items={GROUPS} />
        <div className="w-full max-w-xs"><Input leading={<Search />} aria-label="Search items" placeholder="Search item" value={text} onChange={(e) => setText(e.target.value)} /></div>
        <div className="w-56"><StorePicker value={f.storeId || null} onChange={(id) => setF({ ...f, storeId: id ?? 0 })} placeholder="All my stores" /></div>
        <ProjectPicker value={f.projectId} onChange={(projectId) => setF((x) => ({ ...x, projectId }))} allowAll className="w-56" />
        <div className="w-40">
          <Select aria-label="Category" value={f.category} options={[{ value: '', label: 'Every category' }, ...['CONSUMABLE', 'RETURNABLE', 'TOOL', 'SPARE'].map((c) => ({ value: c, label: c[0] + c.slice(1).toLowerCase() }))]} onChange={(e) => setF({ ...f, category: e.target.value })} />
        </div>
        <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={f.includeZero} onChange={(e) => setF({ ...f, includeZero: e.target.checked })} /> Show empty</label>
      </div>
      {f.group === 'store' ? (
        <DataTable
          label="Stock by store"
          rows={(b.data?.group === 'store' ? b.data.rows : []) as StoreBalance[]}
          columns={byStore}
          rowKey={(r) => `${r.store_id}-${r.item_id}`}
          loading={b.isPending}
          onRowClick={(r) => nav(`${BASE}/items/${r.item_id}?store=${r.store_id}`)}
          empty="Nothing held in the stores you work in."
        />
      ) : (
        <DataTable
          label={f.group === 'item' ? 'Stock by item' : 'Stock by project'}
          rows={(b.data?.group === f.group ? b.data.rows : []) as GroupedBalance[]}
          columns={grouped}
          rowKey={(r) => `${r.project_id ?? 0}-${r.item_id}`}
          loading={b.isPending}
          onRowClick={(r) => nav(`${BASE}/items/${r.item_id}/where`)}
          empty="Nothing held in the stores you work in."
        />
      )}
      <p className="mt-3 text-xs text-muted-foreground">Open a line for its ledger card. Quantities are in each item's base unit.</p>
    </div>
  )
}

function ItemCardPage() {
  const { itemId } = useParams()
  const [sp, setSp] = useSearchParams()
  const id = Number(itemId)
  const storeId = Number(sp.get('store')) || 0
  const from = sp.get('from') ?? ''
  const to = sp.get('to') ?? ''
  const where = useAvailability(id)
  const card = useItemCard(id, storeId, from, to)
  const nav = useNavigate()
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp)
    if (v) next.set(k, v)
    else next.delete(k)
    setSp(next, { replace: true })
  }
  // Opened without a store: the one holding most of it.
  useEffect(() => {
    if (!storeId && where.data?.stores.length) set('store', String(where.data.stores[0].store_id))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId, where.data])
  const c = card.data
  const uom = c?.item.base_uom ?? where.data?.item.base_uom ?? ''
  const cols: TableColumn<CardRow>[] = [
    { id: 'date', header: 'Date', width: '7rem', cell: (r) => formatDate(r.txn_date) },
    {
      id: 'what',
      header: 'Movement',
      cell: (r) => (
        <div>
          <span className={cn(r.reversal_of_id && 'italic')}>{r.reversal_of_id && <Undo2 className="mr-1 inline size-3.5" />}{r.label}</span>
          {r.reversed_by_id && <Badge className="ml-2" tone="warning">reversed</Badge>}
          <div className="text-xs text-muted-foreground">{[r.project, r.cost_head?.replace(/_/g, ' ').toLowerCase(), r.user].filter(Boolean).join(' · ')}</div>
        </div>
      ),
    },
    { id: 'doc', header: 'Document', cell: (r) => (r.doc_path ? <Link className="font-mono text-xs text-primary hover:underline" to={r.doc_path} onClick={(e) => e.stopPropagation()}>{r.doc_number}</Link> : <span className="font-mono text-xs">{r.doc_number}</span>) },
    { id: 'in', header: 'In', align: 'right', cell: (r) => (r.direction === 'IN' ? <span className="text-success">{Number(r.qty_in).toLocaleString('en-IN', { maximumFractionDigits: 3 })}</span> : '') },
    { id: 'out', header: 'Out', align: 'right', cell: (r) => (r.direction === 'OUT' ? <span className="text-danger">{Number(r.qty_out).toLocaleString('en-IN', { maximumFractionDigits: 3 })}</span> : '') },
    { id: 'rate', header: 'Rate', align: 'right', hideBelow: 'lg', cell: (r) => formatINR(Number(r.rate)) },
    { id: 'value', header: 'Value', align: 'right', hideBelow: 'md', cell: (r) => money(r.signed_value) },
    { id: 'bal', header: 'Balance', align: 'right', cell: (r) => <div><strong>{qty(r.running_qty, uom)}</strong><div className="text-xs text-muted-foreground">{money(r.running_value)}</div></div> },
  ]
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Button size="icon-sm" variant="ghost" aria-label="Back to balances" onClick={() => nav(BASE)}><ArrowLeft /></Button>
          <div>
            <h2 className="text-lg font-semibold">{c ? `${c.item.code} ${c.item.name}` : where.data ? `${where.data.item.code} ${where.data.item.name}` : 'Item card'}</h2>
            <Link className="text-xs text-primary hover:underline" to={`${BASE}/items/${id}/where`}>Where else is it held?</Link>
          </div>
        </div>
        {c && <Button variant="outline" size="sm" asChild><a href={`/api/store/enquiry${cardPath(id, storeId, from, to, true)}`} target="_blank" rel="noopener"><FileText /> Print card</a></Button>}
      </div>
      <Card className="grid gap-3 p-4 sm:grid-cols-[1.5fr_1fr_1fr_1.5fr]">
        <Field label="Item" htmlFor="card-item">
          <ItemPicker id="card-item" value={c ? { id: c.item.id, code: c.item.code, name: c.item.name, base_uom: c.item.base_uom, uoms: [], category: null } : null} onChange={(it) => it && nav(`${BASE}/items/${it.id}?store=${storeId}`)} />
        </Field>
        <Field label="From" htmlFor="card-from"><Input id="card-from" type="date" value={from} onChange={(e) => set('from', e.target.value)} /></Field>
        <Field label="To" htmlFor="card-to"><Input id="card-to" type="date" value={to} onChange={(e) => set('to', e.target.value)} /></Field>
        <Field label="Store" htmlFor="card-store"><StorePicker id="card-store" value={storeId || null} onChange={(sid) => set('store', sid ? String(sid) : '')} /></Field>
      </Card>
      {c && (
        <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
          <Stat label={from ? `Before ${formatDate(from)}` : 'Opening'} value={qty(c.opening.qty, uom)} sub={money(c.opening.value)} />
          <Stat label="In" value={qty(c.totals.qty_in, uom)} />
          <Stat label="Out" value={qty(c.totals.qty_out, uom)} />
          <Stat label={to ? `At ${formatDate(to)}` : 'Now'} value={qty(c.closing.qty, uom)} sub={`${money(c.closing.value)} · avg ${formatINR(Number(c.balance.avg_rate))}`} />
        </StatGrid>
      )}
      <DataTable
        label="Ledger card"
        rows={c?.rows ?? []}
        columns={cols}
        rowKey={(r) => r.id}
        loading={!!storeId && card.isPending}
        rowClassName={(r) => (r.reversal_of_id || r.reversed_by_id ? 'text-muted-foreground' : undefined)}
        empty={storeId ? 'No movements in this period.' : 'Choose a store.'}
      />
      {c?.truncated && <p className="text-xs text-warning">Only the first 5,000 movements are shown; narrow the dates.</p>}
    </div>
  )
}

function AvailabilityPage() {
  const { itemId } = useParams()
  const id = Number(itemId)
  const q = useAvailability(id)
  const nav = useNavigate()
  const d = q.data
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button size="icon-sm" variant="ghost" aria-label="Back to balances" onClick={() => nav(BASE)}><ArrowLeft /></Button>
        <h2 className="text-lg font-semibold">{d ? `Where ${d.item.code} ${d.item.name} is held` : 'Where it is held'}</h2>
      </div>
      {d && (
        <StatGrid className="lg:grid-cols-3 xl:grid-cols-3">
          <Stat label="Held in all" value={qty(d.total.qty, d.item.base_uom)} />
          <Stat label="Worth" value={money(d.total.value)} />
          <Stat label="Average rate" value={formatINR(Number(d.total.avg_rate))} />
        </StatGrid>
      )}
      <DataTable
        label="Stores"
        rows={d?.stores ?? []}
        rowKey={(r) => r.store_id}
        loading={q.isPending}
        onRowClick={(r) => nav(`${BASE}/items/${id}?store=${r.store_id}`)}
        rowClassName={(r) => (Number(r.qty) ? undefined : 'text-muted-foreground')}
        columns={[
          { id: 'store', header: 'Store', cell: (r) => <div><span className="font-mono font-semibold">{r.store_code}</span> {r.store_name}{r.project && <div className="text-xs text-muted-foreground">{r.project}</div>}</div> },
          { id: 'qty', header: 'On hand', align: 'right', cell: (r) => <strong>{qty(r.qty, d?.item.base_uom ?? '')}</strong> },
          { id: 'rate', header: 'Avg rate', align: 'right', hideBelow: 'md', cell: (r) => formatINR(Number(r.avg_rate)) },
          { id: 'value', header: 'Value', align: 'right', cell: (r) => money(r.value) },
        ]}
        empty="You work in no store."
      />
    </div>
  )
}
