import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, FileSpreadsheet } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, Card, Field, Input, Skeleton, Stat, StatGrid, Tabs } from '@/components/ui'
import { dayBookXlsx, trialBalanceXlsx, useDayBook, useTrialBalance, type DayVoucher, type TbLedger } from '@/api/books'
import { financialYearStart, formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

type Tab = 'trial' | 'day'
const TABS: Tab[] = ['trial', 'day']

/** A day before or after a yyyy-mm-dd one. */
function shift(iso: string, days: number) {
  const d = new Date(`${iso}T00:00:00`)
  d.setDate(d.getDate() + days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** A balance as a person reads it in the books: the amount, and which side it stands on. Nothing at all when it is nil. */
const side = (dr: number, cr: number) => (dr ? `${formatINR(dr)} Dr` : cr ? `${formatINR(cr)} Cr` : '')
const money = 'tabular whitespace-nowrap'

/**
 * The books as accounts checks them before they go to Tally: the trial balance (every ledger, with where it stood, what the
 * period did to it and where it ends) and the day book (every voucher of a day with its ledger lines). Both are read from
 * the very vouchers Tally is sent, so what is checked here is what goes across.
 */
export default function BooksPage() {
  const [params, setParams] = useSearchParams()
  const tab = (TABS.find((t) => t === params.get('tab')) ?? 'trial') as Tab
  const setTab = (t: Tab) => setParams((p) => { const n = new URLSearchParams(p); if (t === 'trial') n.delete('tab'); else n.set('tab', t); return n }, { replace: true })
  return (
    <>
      <PageHeader eyebrow="Accounts" title="Trial Balance & Day Book" description="Check the books before they go to Tally: every ledger with its opening, debits, credits and closing, and every voucher of a day." />
      <div className="mb-5 max-w-sm">
        <Tabs label="Books" value={tab} onChange={setTab} items={[{ value: 'trial', label: 'Trial balance' }, { value: 'day', label: 'Day book' }]} />
      </div>
      {tab === 'trial' ? <TrialBalanceTab /> : <DayBookTab />}
    </>
  )
}

function Warnings({ list }: { list: string[] }) {
  return <>{list.map((w) => <p key={w} role="alert" className="mb-3 rounded-lg border border-danger/40 bg-danger-soft px-3 py-2 text-[13px] text-danger">{w}</p>)}</>
}

function TrialBalanceTab() {
  const [from, setFrom] = useState(financialYearStart())
  const [to, setTo] = useState(today())
  const q = useTrialBalance(from, to)
  const r = q.data
  const t = r?.totals
  const rows = useMemo(() => r?.ledgers ?? [], [r])
  const filters = useListFilters(rows, { search: (l) => `${l.ledger} ${l.group}`, facets: { group: { label: 'Group', get: (l) => l.group } } })
  const columns: TableColumn<TbLedger>[] = [
    { id: 'ledger', header: 'Ledger', sort: (l) => l.ledger.toLowerCase(), cell: (l) => <div><div className="font-medium">{l.ledger}</div><div className="text-xs text-muted-foreground">{l.group}</div></div> },
    { id: 'open', header: 'Opening', align: 'right', hideBelow: 'md', cell: (l) => <span className={money}>{side(l.opening_dr, l.opening_cr)}</span> },
    { id: 'dr', header: 'Debit', align: 'right', sort: (l) => l.debit, cell: (l) => <span className={money}>{l.debit ? formatINR(l.debit) : ''}</span> },
    { id: 'cr', header: 'Credit', align: 'right', sort: (l) => l.credit, cell: (l) => <span className={money}>{l.credit ? formatINR(l.credit) : ''}</span> },
    { id: 'close', header: 'Closing', align: 'right', sort: (l) => l.closing_dr || -l.closing_cr, cell: (l) => <span className={`${money} font-semibold`}>{side(l.closing_dr, l.closing_cr)}</span> },
  ]
  return (
    <>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="From" htmlFor="tb-from"><Input id="tb-from" type="date" className="w-40" value={from} max={to} onChange={(e) => e.target.value && setFrom(e.target.value)} /></Field>
          <Field label="To" htmlFor="tb-to"><Input id="tb-to" type="date" className="w-40" value={to} min={from} onChange={(e) => e.target.value && setTo(e.target.value)} /></Field>
        </div>
        <Button variant="outline" asChild><a href={trialBalanceXlsx(from, to)}><FileSpreadsheet /> Excel</a></Button>
      </div>

      <StatGrid>
        <Stat label="Total debit" value={formatINR(t?.debit)} loading={q.isPending} sub={r ? `${r.vouchers} vouchers in the period` : undefined} />
        <Stat label="Total credit" value={formatINR(t?.credit)} loading={q.isPending} />
        <Stat label="Closing, debit side" value={formatINR(t?.closing_dr)} loading={q.isPending} />
        <Stat label="Closing, credit side" value={formatINR(t?.closing_cr)} loading={q.isPending} />
        <Stat label="Books" value={r ? (r.balanced ? 'Balanced' : `Out by ${formatINR(r.difference)}`) : undefined} loading={q.isPending} tone={r ? (r.balanced ? 'success' : 'danger') : undefined} sub="debit equals credit" />
      </StatGrid>

      {r && <Warnings list={r.warnings} />}
      <FilterBar filters={filters} placeholder="Search a ledger or a group..." />
      <DataTable
        label="Trial balance" rows={filters.filtered} columns={columns} rowKey={(l) => l.ledger} loading={q.isPending}
        empty={filters.active ? 'Nothing matches those filters.' : 'No vouchers up to the end of this period.'}
        footer={t && !filters.active ? (
          <tr className="border-t-2 border-border font-semibold">
            <td className="px-3 py-2">Total</td>
            <td className="hidden px-3 py-2 text-right md:table-cell"><span className={money}>{side(t.opening_dr, 0)}{t.opening_dr && t.opening_cr ? ' / ' : ''}{side(0, t.opening_cr)}</span></td>
            <td className="px-3 py-2 text-right"><span className={money}>{formatINR(t.debit)}</span></td>
            <td className="px-3 py-2 text-right"><span className={money}>{formatINR(t.credit)}</span></td>
            <td className="px-3 py-2 text-right"><span className={money}>{formatINR(t.closing_dr)} Dr / {formatINR(t.closing_cr)} Cr</span></td>
          </tr>
        ) : undefined}
      />

      {!!r?.left_out.length && (
        <Card className="mt-5 p-4">
          <h2 className="text-sm font-semibold">Not in these books yet</h2>
          <p className="mb-3 text-xs text-muted-foreground">Recorded in the period, but not a voucher until the step named is done. Do them before you send the books to Tally.</p>
          <ul className="divide-y divide-border text-sm">
            {r.left_out.map((l) => (
              <li key={l.what} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2">
                <div className="min-w-0"><span className="font-medium">{l.count} {l.what}</span><span className="block text-xs text-muted-foreground">{l.why}</span></div>
                <div className="flex items-center gap-3"><span className="tabular-nums">{formatINR(l.amount)}</span><Link to={l.where} className="text-[13px] text-primary underline underline-offset-4">Open</Link></div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  )
}

function VoucherCard({ v }: { v: DayVoucher }) {
  return (
    <Card className={`mb-3 overflow-hidden ${v.cancelled ? 'opacity-60' : ''}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-muted/40 px-4 py-2">
        <Badge tone={v.cancelled ? 'danger' : 'neutral'}>{v.type}{v.cancelled ? ' cancelled' : ''}</Badge>
        <span className="font-mono text-[13px] font-medium">{v.number}</span>
        {v.project && <span className="text-xs text-muted-foreground">{v.project}</span>}
        <span className="ml-auto text-xs text-muted-foreground">{v.cancelled ? 'cancelled in Tally' : formatINR(v.amount)}</span>
      </div>
      {v.narration && <p className="px-4 pt-2 text-[13px] text-muted-foreground">{v.narration}</p>}
      {!!v.lines.length && (
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground"><tr><th className="px-4 pb-1 pt-2">Ledger</th><th className="px-4 pb-1 pt-2 text-right">Debit</th><th className="px-4 pb-1 pt-2 text-right">Credit</th></tr></thead>
          <tbody>
            {v.lines.map((l, i) => (
              <tr key={i} className="border-t border-border">
                <td className={`px-4 py-1.5 ${l.credit ? 'pl-8' : ''}`}>{l.ledger}</td>
                <td className="px-4 text-right tabular-nums">{l.debit ? formatINR(l.debit) : ''}</td>
                <td className="px-4 text-right tabular-nums">{l.credit ? formatINR(l.credit) : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}

function DayBookTab() {
  const [day, setDay] = useState(today())
  const q = useDayBook(day)
  const d = q.data
  const s = d?.summary
  return (
    <>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-2">
          <Button variant="outline" size="icon" aria-label="The day before" onClick={() => setDay(shift(day, -1))}><ChevronLeft /></Button>
          <Field label="Day" htmlFor="db-day"><Input id="db-day" type="date" className="w-40" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} /></Field>
          <Button variant="outline" size="icon" aria-label="The day after" onClick={() => setDay(shift(day, 1))}><ChevronRight /></Button>
          {day !== today() && <button type="button" className="pb-2 text-xs font-medium text-primary underline underline-offset-4" onClick={() => setDay(today())}>Today</button>}
        </div>
        <Button variant="outline" asChild><a href={dayBookXlsx(day)}><FileSpreadsheet /> Excel</a></Button>
      </div>

      <StatGrid>
        <Stat label="Vouchers" value={s?.count ?? 0} loading={q.isPending} sub={s?.cancelled ? `${s.cancelled} cancelled` : formatDate(day)} />
        <Stat label="Total debit" value={formatINR(s?.debit)} loading={q.isPending} />
        <Stat label="Total credit" value={formatINR(s?.credit)} loading={q.isPending} />
      </StatGrid>
      {!!s?.types.length && <p className="-mt-3 mb-4 text-xs text-muted-foreground">{s.types.map((t) => `${t.count} ${t.type}${t.count === 1 ? '' : 's'}`).join(' · ')}</p>}

      {d && <Warnings list={d.warnings} />}
      {q.isPending ? <Skeleton className="h-40 w-full" /> : !d?.vouchers.length ? (
        <Card className="p-6 text-sm text-muted-foreground">Nothing was booked on {formatDate(day)}.</Card>
      ) : (
        d.vouchers.map((v) => <VoucherCard key={`${v.type}-${v.number}-${v.cancelled}`} v={v} />)
      )}
    </>
  )
}
