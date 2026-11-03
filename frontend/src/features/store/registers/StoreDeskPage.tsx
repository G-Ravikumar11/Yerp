import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowDownToLine, ArrowUpFromLine, Boxes, TriangleAlert } from 'lucide-react'
import { STORE_DESK_PERM } from '@/lib/nav'
import { StoreSections } from './StoreSections'
import { Stat, StatGrid, Tabs } from '@/components/ui'
import { PageHeader } from '@/components/layout/PageHeader'
import { useSession } from '@/lib/session'
import { storePerm, useStoreOptions } from '@/api/store'
import { StorePicker } from '../shared'
import { inLakhs, isLow, useIssues, useReceipts, useStock } from './api'
import { StockRegister } from './StockRegisterPage'
import { ReceiveList } from './ReceiveRegisterPage'
import { IssueList } from './IssueRegisterPage'
import { LowStockList } from './LowStockPage'

type Tab = 'stock' | 'received' | 'issued' | 'low'
const TABS: Tab[] = ['stock', 'received', 'issued', 'low']
const KEPT = 'store-desk-store'
const today = () => new Date().toISOString().slice(0, 10)

/** The store this person last worked in, kept on this device. */
function rememberedStore() {
  try { return Number(localStorage.getItem(KEPT) || 0) } catch { return 0 }
}

/**
 * The Store page, the menu's one Store entry. At the top the Store Desk: the whole day's store work on one page, for people who should not have to hunt through menus.
 * Two big buttons for the two jobs done most (material in, material out), today's figures, and the four lists as
 * tabs. Choose the store once; it is remembered, and chosen for you when you work in only one. The lists fetch fresh
 * figures every minute by themselves.
 */
export default function StoreDeskPage() {
  const { can } = useSession()
  if (!can(STORE_DESK_PERM)) return (
    <div>
      <PageHeader eyebrow="Store" title="Store" description="Purchase and the rest of the store, from one place." />
      <StoreSections />
    </div>
  )
  return <StoreDesk />
}

/** The day's work: choose the store once, two big buttons, today's figures and the four lists; then everything else. */
function StoreDesk() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const tab = (TABS.includes(params.get('tab') as Tab) ? params.get('tab') : 'stock') as Tab
  const setTab = (t: Tab) => setParams((p) => { const n = new URLSearchParams(p); n.set('tab', t); return n }, { replace: true })
  const stores = useStoreOptions(0)
  const [storeId, setStoreId] = useState(rememberedStore)
  // Only one store to work in: it is the one, without asking.
  useEffect(() => {
    const mine = stores.data ?? []
    if (mine.length === 1 && storeId !== mine[0].id) setStoreId(mine[0].id)
    if (storeId && mine.length && !mine.some((s) => s.id === storeId)) setStoreId(0)
  }, [stores.data, storeId])
  useEffect(() => { try { localStorage.setItem(KEPT, String(storeId)) } catch { /* private window */ } }, [storeId])

  const stock = useStock({ store_id: storeId, category: '' })
  const lowAll = useStock({ store_id: storeId, category: '', include_zero: true })
  const received = useReceipts(storeId)
  const issued = useIssues(storeId)
  const items = new Set((stock.data?.items ?? []).map((r) => r.item_id)).size
  const low = (lowAll.data?.items ?? []).filter(isLow).length
  const inToday = (received.data?.items ?? []).filter((r) => r.date === today()).length
  const outToday = (issued.data?.items ?? []).filter((r) => r.date === today()).length
  const withStore = storeId ? `?store=${storeId}` : ''

  return (
    <div>
      <PageHeader eyebrow="Store" title="Store" description="Receive material, issue material and see what is in the store - and everything else in the store below." />
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <label htmlFor="desk-store" className="text-sm font-medium">Store</label>
        <div className="w-full sm:w-72"><StorePicker id="desk-store" value={storeId || null} placeholder="All my stores" onChange={(id) => setStoreId(id ?? 0)} /></div>
      </div>
      <div className="mb-6 grid gap-3 sm:grid-cols-2">
        {can(storePerm('inward', 'create')) && (
          <Link to={`/store/receive/new${withStore}`} className="flex items-center gap-4 rounded-2xl border border-success/40 bg-success-soft p-5 text-success transition hover:border-success focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <ArrowDownToLine className="size-9 shrink-0" />
            <span><span className="block text-lg font-semibold">Receive material</span><span className="text-sm text-muted-foreground">Material has arrived at the store</span></span>
          </Link>
        )}
        {can(storePerm('outward', 'create')) && (
          <Link to={`/store/issue/new${withStore}`} className="flex items-center gap-4 rounded-2xl border border-primary/40 bg-primary/10 p-5 text-primary transition hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <ArrowUpFromLine className="size-9 shrink-0" />
            <span><span className="block text-lg font-semibold">Issue material</span><span className="text-sm text-muted-foreground">Material is going out to site</span></span>
          </Link>
        )}
      </div>
      <StatGrid className="lg:grid-cols-5 xl:grid-cols-5">
        <Stat label="Materials in stock" value={items.toLocaleString('en-IN')} loading={stock.isPending} onClick={() => setTab('stock')} active={tab === 'stock'} />
        <Stat label="Stock value" value={inLakhs(Number(stock.data?.total_value ?? 0))} tone="success" loading={stock.isPending} />
        <Stat label="Received today" value={inToday} loading={received.isPending} onClick={() => setTab('received')} active={tab === 'received'} />
        <Stat label="Issued today" value={outToday} loading={issued.isPending} onClick={() => setTab('issued')} active={tab === 'issued'} />
        <Stat label="Low stock" value={low} tone={low ? 'danger' : undefined} loading={lowAll.isPending} onClick={() => setTab('low')} active={tab === 'low'} sub={low ? 'Order these soon' : 'Nothing is low'} />
      </StatGrid>
      <div className="mb-4">
        <Tabs size="lg" label="Store lists" value={tab} onChange={setTab} items={[
          { value: 'stock', label: 'Stock', count: items },
          { value: 'received', label: 'Received', count: received.data?.items.length },
          { value: 'issued', label: 'Issued', count: issued.data?.items.length },
          { value: 'low', label: 'Low stock', count: low },
        ]} />
      </div>
      {tab === 'stock' && <StockRegister embedded storeId={storeId} />}
      {tab === 'received' && <ReceiveList storeId={storeId} />}
      {tab === 'issued' && <IssueList storeId={storeId} />}
      {tab === 'low' && <LowStockList storeId={storeId} />}
      <p className="mt-6 flex items-center gap-2 text-xs text-muted-foreground">
        <Boxes className="size-4" /> These lists update by themselves every minute.
        {low > 0 && <span className="flex items-center gap-1 text-danger"><TriangleAlert className="size-3.5" /> {low} low</span>}
      </p>
      <div className="mt-8"><StoreSections /></div>
    </div>
  )
}
