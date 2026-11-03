import { lazy, Suspense } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowUpRight, Banknote, CreditCard, Landmark, Sparkles, TrendingUp, Wallet } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton, Stat, StatGrid } from '@/components/ui'
import { attentionHref, useAttention, useBalanceSheet, useCashFlow, usePayables, useProfitLoss, useReceivables, type AttentionItem } from '@/api/dashboard'
import { Figure } from '@/features/dashboard/Figure'
import { monthLabel } from '@/lib/cashflow'
import { useSession } from '@/lib/session'
import { compactINR } from '@/lib/utils'

// The chart library is the heaviest thing on this page, and the tiles above it should not wait for it.
const CashFlowChart = lazy(() => import('@/features/dashboard/Charts').then((m) => ({ default: m.CashFlowChart })))
const RevenueExpenseChart = lazy(() => import('@/features/dashboard/Charts').then((m) => ({ default: m.RevenueExpenseChart })))

const ChartSkeleton = () => <Skeleton className="h-[210px] w-full" />
const Empty = ({ children }: { children: React.ReactNode }) => <p className="grid h-40 place-items-center text-center text-sm text-muted-foreground">{children}</p>

function Insight({ item }: { item: AttentionItem }) {
  const link = attentionHref(item.view)
  const body = (
    <div className="rounded-lg border border-border bg-card p-3.5 transition-colors hover:bg-accent">
      <Badge tone="ember">Finance</Badge>
      <p className="mt-2 text-[13.5px] font-semibold leading-snug">{item.title}</p>
      <p className="mt-1 text-[13px] text-muted-foreground">{item.detail}</p>
      <span className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary">
        View details <ArrowUpRight className="size-3" />
      </span>
    </div>
  )
  return link.external ? <a href={link.to}>{body}</a> : <Link to={link.to}>{body}</Link>
}

/** The accounts at a glance: what is owed in and out, what has been spent, what cash the business holds, and the
 * trend behind it - the single screen a finance person opens first, instead of totting up every ledger by hand. */
export default function FinanceDashboardPage() {
  const { can } = useSession()
  const money = can('bills.view_all')
  const reports = can('reports.view')

  const receivables = useReceivables(money)
  const payables = usePayables(money)
  const profitLoss = useProfitLoss(reports)
  const balance = useBalanceSheet(reports)
  const cash = useCashFlow(money)
  const attention = useAttention()

  const overdueCount = (rows: { bucket: string }[] | undefined) => (rows ?? []).filter((r) => r.bucket !== 'Not due').length
  const overdueEntries = overdueCount(receivables.data?.invoices) + overdueCount(payables.data?.bills)
  const overdueAmount = (receivables.data?.summary.overdue ?? 0) + (payables.data?.summary.overdue ?? 0)
  const cashHasData = (cash.data ?? []).some((m) => m.received || m.paid)
  // The last twelve months with any activity, so the chart reads like a trend rather than the whole company's history.
  const allMonths = profitLoss.data?.months ?? []
  const start = Math.max(0, allMonths.length - 12)
  const revExp = allMonths.slice(start).map((m, i) => ({ month: m, label: monthLabel(m), revenue: profitLoss.data?.revenue[start + i] ?? 0, expense: profitLoss.data?.expenses[start + i] ?? 0 }))
  const insights = (attention.data?.items ?? []).filter((i) => i.severity === 'money').slice(0, 4)
  const fig = (n: number | undefined, loading: boolean) => (loading ? undefined : <Figure value={n ?? 0} format={compactINR} />)

  return (
    <>
      <PageHeader eyebrow="Accounts" title="Finance Dashboard" description="Receivables, payables, expenses and cash position across every project." actions={<Button variant="outline" asChild><Link to="/money/cash-flow"><TrendingUp /> Cash flow by month</Link></Button>} />

      <StatGrid>
        {money && (
          <>
            <Stat
              label="Total Receivables"
              to="/money/owed?tab=owed"
              value={fig(receivables.data?.summary.owed, receivables.isPending)}
              loading={receivables.isPending}
              sub={receivables.data ? `${compactINR(receivables.data.summary.overdue)} overdue` : undefined}
            />
            <Stat
              label="Total Payables"
              to="/money/owed?tab=owe"
              value={fig(payables.data?.summary.owed, payables.isPending)}
              loading={payables.isPending}
              sub={payables.data ? `${compactINR(payables.data.summary.overdue)} overdue` : undefined}
            />
          </>
        )}
        {reports && (
          <>
            <Stat
              label="Total Expenses"
              to="/money/ledgers"
              value={fig(profitLoss.data?.total_expenses, profitLoss.isPending)}
              loading={profitLoss.isPending}
              sub="Bills, subcontractor bills and vouchers, all time"
            />
            <Stat
              label="Cash Position"
              to="/money/ledgers"
              value={fig(balance.data?.assets.bank_and_cash, balance.isPending)}
              loading={balance.isPending}
              sub="Every bank account and cash box, today"
            />
          </>
        )}
        {money && (
          <Stat
            label="Overdue Amount"
            to="/money/owed"
            value={fig(overdueAmount, receivables.isPending || payables.isPending)}
            loading={receivables.isPending || payables.isPending}
            tone={overdueAmount > 0 ? 'danger' : undefined}
            sub={receivables.data && payables.data ? `${overdueEntries} ${overdueEntries === 1 ? 'entry' : 'entries'}` : undefined}
          />
        )}
      </StatGrid>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="size-4 text-primary" /> AI Finance Insights
            </CardTitle>
            <CardDescription>Generated from what the books show right now.</CardDescription>
          </CardHeader>
          <CardContent>
            {attention.isPending ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24 w-full" />)}
              </div>
            ) : attention.isError ? (
              <Empty>Could not load this.</Empty>
            ) : insights.length === 0 ? (
              <Empty>Nothing stands out on the books right now.</Empty>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {insights.map((i) => <Insight key={i.kind + i.title} item={i} />)}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="size-4 text-warning" /> At a glance
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm">
            <p className="flex items-center gap-2 text-muted-foreground"><Landmark className="size-4 shrink-0" /> Receivables are what clients owe us; payables are what we owe suppliers and subcontractors.</p>
            <p className="flex items-center gap-2 text-muted-foreground"><CreditCard className="size-4 shrink-0" /> Expenses are accrual - booked when billed to us, not when paid.</p>
            <p className="flex items-center gap-2 text-muted-foreground"><Wallet className="size-4 shrink-0" /> Cash position is every bank account and cash box, as of today.</p>
            <p className="flex items-center gap-2 text-muted-foreground"><Banknote className="size-4 shrink-0" /> Overdue amount is past-due receivables and payables added together.</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Cash Flow Trend</CardTitle>
            <CardDescription>Monthly money in against money out, with the running balance.</CardDescription>
          </CardHeader>
          <CardContent>
            {!money ? (
              <Empty>Needs access to Accounts.</Empty>
            ) : cash.isPending ? (
              <ChartSkeleton />
            ) : cash.isError ? (
              <Empty>Could not load the ledger.</Empty>
            ) : !cashHasData ? (
              <Empty>Nothing received or paid in the last twelve months.</Empty>
            ) : (
              <Suspense fallback={<ChartSkeleton />}>
                <CashFlowChart months={cash.data} />
              </Suspense>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Revenue vs Expense</CardTitle>
            <CardDescription>Monthly comparison, on the accrual basis.</CardDescription>
          </CardHeader>
          <CardContent>
            {!reports ? (
              <Empty>Needs access to Reports.</Empty>
            ) : profitLoss.isPending ? (
              <ChartSkeleton />
            ) : profitLoss.isError ? (
              <Empty>Could not load this.</Empty>
            ) : revExp.length === 0 ? (
              <Empty>Nothing billed yet.</Empty>
            ) : (
              <Suspense fallback={<ChartSkeleton />}>
                <RevenueExpenseChart months={revExp} />
              </Suspense>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  )
}
