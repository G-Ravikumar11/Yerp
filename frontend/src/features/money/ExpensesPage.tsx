import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { Download, Eye, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton } from '@/components/ui'
import { useEntries, voucherUrl, type Entry } from '@/api/ledger'
import { usePaymentRequests, type PaymentRequest, type RequestStatus } from '@/api/payments'
import { projectLabel, useProjects } from '@/api/projects'
import { ExpenseModal } from '@/features/ledger/VoucherModals'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { downloadCsv, formatINR } from '@/lib/utils'

const SLICES = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)']
const REQUEST_TONE: Record<RequestStatus, 'warning' | 'info' | 'success' | 'neutral' | 'danger' | 'ember'> = {
  PENDING: 'warning', AWAITING_MD: 'ember', APPROVED: 'info', PAID: 'success', REJECTED: 'danger', CANCELLED: 'neutral',
}

interface Row {
  key: string
  number: string
  party: string
  project: string
  amount: number
  date: string
  head: string
  status: string
  tone: 'warning' | 'info' | 'success' | 'neutral' | 'danger' | 'ember'
  /** An already-paid voucher opens its printed voucher; a request still waiting opens the requests tab to decide it. */
  href: string
  external: boolean
}

/** Every operating expense - site overheads, equipment rentals, diesel, the rest - what it was paid to, which project it
 * was charged to, when, under what head, and whether it has been paid yet or is still waiting on a decision. */
export default function ExpensesPage() {
  const { can } = useSession()
  const entries = useEntries()
  const requests = usePaymentRequests()
  const projects = useProjects()
  const [raising, setRaising] = useState(false)

  const jobName = useMemo(() => Object.fromEntries((projects.data ?? []).map((p) => [p.id, projectLabel(p)])), [projects.data])

  const rows: Row[] = useMemo(() => {
    const paid: Row[] = (entries.data?.entries ?? [])
      .filter((e): e is Entry => e.doc_type === 'expense')
      .map((e) => ({
        key: `entry-${e.id}`, number: e.number, party: e.party_name || '-', project: e.job_id ? jobName[e.job_id] ?? '' : 'Head office',
        amount: e.amount, date: e.paid_on, head: e.head || 'Other', status: e.voided ? 'Voided' : 'Paid',
        tone: e.voided ? 'neutral' : 'success', href: voucherUrl(e.id), external: true,
      }))
    // A request not yet paid: it becomes the entry above once it is, so only the still-open ones are added here.
    const open: Row[] = (requests.data?.requests ?? [])
      .filter((r): r is PaymentRequest => r.doc_type === 'expense' && r.status !== 'PAID')
      .map((r) => ({
        key: `request-${r.id}`, number: r.number, party: r.party_name || '-', project: r.project || 'Head office',
        amount: r.amount, date: r.requested_at, head: r.head || 'Other', status: r.status_label || r.status,
        tone: REQUEST_TONE[r.status], href: '/money/ledgers?tab=requests', external: false,
      }))
    return [...paid, ...open].sort((a, b) => (b.date || '').localeCompare(a.date || ''))
  }, [entries.data, requests.data, jobName])

  const categories = useMemo(() => {
    const by = new Map<string, number>()
    for (const r of rows) if (r.status === 'Paid') by.set(r.head, (by.get(r.head) ?? 0) + r.amount)
    const total = [...by.values()].reduce((n, v) => n + v, 0)
    return [...by.entries()].sort((a, b) => b[1] - a[1]).map(([head, amount]) => ({ head, amount, share: total ? Math.round((amount / total) * 1000) / 10 : 0 }))
  }, [rows])

  const filters = useListFilters(rows, {
    search: (r) => [r.number, r.party, r.project, r.head].join(' '),
    status: (r) => r.status,
    date: (r) => r.date,
    facets: { project: { label: 'Project', get: (r) => r.project } },
  })

  const loading = entries.isPending || requests.isPending
  const columns: TableColumn<Row>[] = [
    { id: 'no', header: 'Entry ID', sort: (r) => r.number, cell: (r) => <span className="font-mono text-[13px]">{r.number}</span> },
    { id: 'party', header: 'Paid To', sort: (r) => r.party, cell: (r) => r.party },
    { id: 'project', header: 'Project', hideBelow: 'md', sort: (r) => r.project, cell: (r) => r.project },
    { id: 'amount', header: 'Amount', align: 'right', sort: (r) => r.amount, cell: (r) => <span className="tabular">{formatINR(r.amount)}</span> },
    { id: 'date', header: 'Date', hideBelow: 'sm', sort: (r) => r.date, cell: (r) => formatDate(r.date) },
    { id: 'head', header: 'Category', hideBelow: 'lg', sort: (r) => r.head, cell: (r) => r.head },
    { id: 'status', header: 'Status', cell: (r) => <Badge tone={r.tone}>{r.status}</Badge> },
    {
      id: 'act', header: '', align: 'right', width: '3rem',
      cell: (r) => (r.external
        ? <Button size="icon-sm" variant="ghost" asChild><a href={r.href} target="_blank" rel="noreferrer" aria-label={`View ${r.number}`}><Eye /></a></Button>
        : <Button size="icon-sm" variant="ghost" asChild><Link to={r.href} aria-label={`View ${r.number}`}><Eye /></Link></Button>),
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Accounts" title="Expenses" description="Site overheads, equipment rentals and other operating expenses."
        actions={
          <>
            <Button variant="outline" disabled={!filters.filtered.length} onClick={() => downloadCsv('expenses', ['Entry ID', 'Paid to', 'Project', 'Amount', 'Date', 'Category', 'Status'], filters.filtered.map((r) => [r.number, r.party, r.project, r.amount, r.date, r.head, r.status]))}>
              <Download /> Export
            </Button>
            {can('bills.pay') && <Button onClick={() => setRaising(true)}><Plus /> New Expense</Button>}
          </>
        }
      />

      <Card className="mb-5">
        <CardHeader>
          <CardTitle>Expense by Category</CardTitle>
          <CardDescription>Share of total spend (paid expenses only).</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-[220px] w-full" />
          ) : categories.length === 0 ? (
            <p className="grid h-40 place-items-center text-sm text-muted-foreground">Nothing paid yet.</p>
          ) : (
            <figure aria-label="Expense by category" className="m-0 h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Tooltip
                    content={({ active, payload }) => {
                      const c = payload?.[0]?.payload as { head: string; amount: number; share: number } | undefined
                      if (!active || !c) return null
                      return (
                        <div className="rounded-lg border border-border bg-popover px-3 py-2.5 text-[13px] shadow-lift">
                          <p className="font-medium">{c.head}</p>
                          <p className="tabular text-muted-foreground">{formatINR(c.amount)} - {c.share}%</p>
                        </div>
                      )
                    }}
                  />
                  <Legend verticalAlign="bottom" iconType="circle" iconSize={8} formatter={(v: string) => <span className="text-xs text-muted-foreground">{v}</span>} />
                  <Pie data={categories} dataKey="amount" nameKey="head" innerRadius="52%" outerRadius="80%" paddingAngle={2} stroke="var(--card)" strokeWidth={2}>
                    {categories.map((c, i) => <Cell key={c.head} fill={SLICES[i % SLICES.length]} />)}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            </figure>
          )}
        </CardContent>
      </Card>

      <FilterBar filters={filters} placeholder="Search by entry, paid to, project or category..." />
      <DataTable
        label="Expenses" rows={filters.filtered} columns={columns} rowKey={(r) => r.key} loading={loading}
        empty={filters.active ? 'Nothing matches those filters.' : 'No expense has been recorded yet.'}
      />
      <ExpenseModal kind={raising ? 'expense' : null} onClose={() => setRaising(false)} />
    </>
  )
}
