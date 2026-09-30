import { useState } from 'react'
import { Download } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, Select, Stat, StatGrid, Tabs } from '@/components/ui'
import { assetKeys, assetsExcel, methodText, setUpAll, useRegister, useTaxBlocks, type AssetBook, type NotSetUp, type TaxBlock } from '@/api/assets'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { cn, compactINR, formatINR } from '@/lib/utils'
import { BookModal, type BookTarget } from './BookModal'
import { BlockModal, DisposeModal, ScheduleModal } from './SmallModals'

type Tab = 'register' | 'blocks'

export default function AssetsPage() {
  const { can } = useSession()
  const [tab, setTab] = useState<Tab>('register')
  const [fy, setFy] = useState('')
  const reg = useRegister(fy)
  const blocks = useTaxBlocks(reg.data?.fy ?? '', tab === 'blocks')
  const [book, setBook] = useState<BookTarget | null>(null)
  const [years, setYears] = useState(0)
  const [selling, setSelling] = useState<{ id: number; title: string } | null>(null)
  const [block, setBlock] = useState<TaxBlock | null>(null)
  const all = useAction(() => setUpAll(), { invalidate: [assetKeys.all] })
  const d = reg.data
  const t = d?.totals
  const manage = can('accounts.manage|bills.view_all')
  const nr = 'tabular whitespace-nowrap'

  const openBook = (a: AssetBook) => setBook({ id: a.asset_id, title: `${a.code} ${a.name}`, setUp: true, book: a })
  const regCols: TableColumn<AssetBook>[] = [
    { id: 'asset', header: 'Asset', cell: (a) => <div><span className="font-mono text-[13px] font-semibold">{a.code}</span><div className="text-xs text-muted-foreground">{a.name}</div></div> },
    { id: 'use', header: 'In use from', hideBelow: 'md', cell: (a) => <div className={nr}>{a.put_to_use_on}<div className="text-xs text-muted-foreground">{methodText(a)}</div></div> },
    { id: 'cost', header: 'Cost', hideBelow: 'lg', align: 'right', cell: (a) => <span className={nr}>{formatINR(a.cost)}</span> },
    { id: 'open', header: 'Opening', hideBelow: 'lg', align: 'right', cell: (a) => <div className={nr}>{formatINR(a.year.opening + a.year.added)}{a.year.added > 0 && <div className="text-xs text-muted-foreground">bought this year</div>}</div> },
    { id: 'dep', header: 'Depreciation', align: 'right', cell: (a) => <div className={nr}>{formatINR(a.year.depreciation)}{a.year.days < 365 && <div className="text-xs text-muted-foreground">{a.year.days} days</div>}</div> },
    { id: 'close', header: 'Closing', align: 'right', cell: (a) => (a.year.disposed ? <div className={nr}>sold {formatINR(a.year.disposal_value ?? 0)}<div className={cn('text-xs', (a.year.gain ?? 0) >= 0 ? 'text-success' : 'text-danger')}>{(a.year.gain ?? 0) >= 0 ? 'profit ' : 'loss '}{formatINR(Math.abs(a.year.gain ?? 0))}</div></div> : <span className={`${nr} font-bold`}>{formatINR(a.year.closing)}</span>) },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (a) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setYears(a.asset_id)}>Years</Button>
          {manage && !a.disposed_on && <><Button size="sm" variant="outline" onClick={() => openBook(a)}>Edit</Button><Button size="sm" variant="outline" onClick={() => setSelling({ id: a.asset_id, title: `${a.code} ${a.name}` })}>Sold</Button></>}
        </div>
      ),
    },
  ]

  const unsetCols: TableColumn<NotSetUp>[] = [
    { id: 'asset', header: 'Asset', cell: (u) => <div><span className="font-mono text-[13px] font-semibold">{u.code}</span> {u.name}</div> },
    { id: 'cat', header: 'Category', hideBelow: 'md', cell: (u) => u.category },
    { id: 'cost', header: 'Bought for', align: 'right', cell: (u) => (u.suggest.cost ? formatINR(u.suggest.cost) : '-') },
    { id: 'on', header: 'On', hideBelow: 'md', cell: (u) => u.suggest.put_to_use_on || '-' },
    { id: 'act', header: '', align: 'right', cell: (u) => (manage ? <Button size="sm" variant="outline" onClick={() => setBook({ id: u.asset_id, title: `${u.code} ${u.name}`, setUp: false, book: u.suggest })}>Set up</Button> : null) },
  ]

  const blockCols: TableColumn<TaxBlock>[] = [
    { id: 'block', header: 'Block', cell: (b) => <div>{b.block}<div className="text-xs text-muted-foreground">{b.rate}%{b.opening_fy ? ` · opened ${b.opening_fy}` : ''}</div></div> },
    { id: 'open', header: 'Opening', hideBelow: 'md', align: 'right', cell: (b) => <span className={nr}>{formatINR(b.opening)}</span> },
    { id: 'added', header: 'Added', align: 'right', cell: (b) => <div className={nr}>{formatINR(b.added_full + b.added_half)}{b.added_half > 0 && <div className="text-xs text-muted-foreground">{formatINR(b.added_half)} at half rate</div>}</div> },
    { id: 'sold', header: 'Sold', hideBelow: 'md', align: 'right', cell: (b) => <span className={nr}>{formatINR(b.deleted)}</span> },
    { id: 'dep', header: 'Depreciation', align: 'right', cell: (b) => <span className={nr}>{formatINR(b.depreciation)}</span> },
    { id: 'close', header: 'Closing', align: 'right', cell: (b) => <div className={`${nr} font-bold`}>{formatINR(b.closing)}{b.short_term_gain > 0 && <div className="text-xs font-normal text-danger">short-term gain {formatINR(b.short_term_gain)}</div>}{b.short_term_loss > 0 && <div className="text-xs font-normal">short-term loss {formatINR(b.short_term_loss)}</div>}</div> },
    { id: 'act', header: '', align: 'right', cell: (b) => (manage ? <Button size="sm" variant="outline" onClick={() => setBlock(b)}>Edit</Button> : null) },
  ]

  const bt = blocks.data?.totals
  return (
    <>
      <PageHeader
        eyebrow="Money"
        title="Fixed Assets"
        description="What each owned asset is worth on the books, and the income-tax blocks the return is filed on."
        actions={
          <>
            {d && <div className="w-36"><Select aria-label="Financial year" value={d.fy} onChange={(e) => setFy(e.target.value)} options={d.fys.map((y) => ({ value: y, label: y }))} /></div>}
            {tab === 'register' && manage && d?.not_set_up.some((u) => u.ready) && <Button variant="outline" loading={all.isPending} onClick={() => all.mutate()}>Set up every ready asset</Button>}
            {d && <Button variant="outline" asChild><a href={assetsExcel(tab, d.fy)}><Download /> Excel</a></Button>}
          </>
        }
      />
      <div className="mb-5"><Tabs label="View" value={tab} onChange={setTab} items={[{ value: 'register', label: 'Register' }, { value: 'blocks', label: 'Income-tax blocks' }]} /></div>

      {tab === 'register' && (
        <>
          <StatGrid>
            <Stat label="Cost" value={compactINR(t?.cost)} loading={reg.isPending} />
            <Stat label={`Depreciation in ${d?.fy ?? ''}`} value={compactINR(t?.depreciation)} loading={reg.isPending} />
            <Stat label="Book value at 31 March" value={compactINR(t?.closing)} loading={reg.isPending} />
            <Stat label="Accumulated" value={compactINR(t?.accumulated)} loading={reg.isPending} />
            {!!t?.gain && <Stat label={`${t.gain >= 0 ? 'Profit' : 'Loss'} on sales`} value={compactINR(Math.abs(t.gain))} />}
          </StatGrid>
          <DataTable label="Asset register" rows={d?.assets ?? []} columns={regCols} rowKey={(a) => a.asset_id} loading={reg.isPending} empty={`Nothing on the books for ${d?.fy ?? 'this year'}. Owned machines from the equipment register appear below until their book is set up.`} />
          {!!d?.not_set_up.length && (
            <>
              <h2 className="mb-3 mt-8 text-base font-semibold">Owned, but no book yet</h2>
              <DataTable label="Assets with no book" rows={d.not_set_up} columns={unsetCols} rowKey={(u) => u.asset_id} />
            </>
          )}
        </>
      )}
      {tab === 'blocks' && (
        <>
          <StatGrid>
            <Stat label="Opening WDV" value={compactINR(bt?.opening)} loading={blocks.isPending} />
            <Stat label="Added" value={compactINR((bt?.added_full ?? 0) + (bt?.added_half ?? 0))} loading={blocks.isPending} />
            <Stat label="Tax depreciation" value={compactINR(bt?.depreciation)} loading={blocks.isPending} />
            <Stat label="Closing WDV" value={compactINR(bt?.closing)} loading={blocks.isPending} />
          </StatGrid>
          <p className="mb-3 text-[13px] text-muted-foreground">As the income-tax return wants it: each block at its rate, half the rate on anything used for less than 180 days in the year it was bought.</p>
          <DataTable label="Income-tax blocks" rows={blocks.data?.blocks ?? []} columns={blockCols} rowKey={(b) => b.block_id} loading={blocks.isPending} />
        </>
      )}

      <BookModal target={book} blocks={d?.blocks ?? []} methods={d?.methods ?? ['WDV', 'SLM']} onClose={() => setBook(null)} />
      {years > 0 && <ScheduleModal assetId={years} onClose={() => setYears(0)} />}
      <DisposeModal key={selling?.id ?? 0} target={selling} onClose={() => setSelling(null)} />
      {block && <BlockModal key={block.block_id} block={block} onClose={() => setBlock(null)} />}
    </>
  )
}
