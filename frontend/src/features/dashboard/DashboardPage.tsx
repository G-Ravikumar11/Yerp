import { lazy, Suspense } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { AlertTriangle, ArrowUpRight, CheckCheck } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton, Stat } from '@/components/ui'
import { useInbox } from '@/api/approvals'
import { attentionHref, useAttention, useCashFlow, usePayables, useProjectPnl, useReceivables, useRetention, type AttentionItem } from '@/api/dashboard'
import { Figure } from './Figure'
import { useSession } from '@/lib/session'
import { compactINR, formatINR } from '@/lib/utils'

// The chart library is the heaviest thing on this page, and the tiles above it should not wait for it.
const ProfitChart = lazy(() => import('./Charts').then((m) => ({ default: m.ProfitChart })))
const CashFlowChart = lazy(() => import('./Charts').then((m) => ({ default: m.CashFlowChart })))
const AgeingChart = lazy(() => import('./Charts').then((m) => ({ default: m.AgeingChart })))

const greeting = () => {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

const SEVERITY: Record<string, { tone: 'danger' | 'warning' | 'neutral' | 'ember'; word: string }> = {
  money: { tone: 'ember', word: 'Money' },
  wrong: { tone: 'danger', word: 'Looks wrong' },
  action: { tone: 'warning', word: 'Needs a decision' },
  notice: { tone: 'neutral', word: 'When you can' },
}

const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.05 } } }
const rise = { hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] as const } } }

/** A panel that says what it is, and what became of it when there was nothing to show. */
function Panel({ title, description, action, className, children }: { title: string; description?: string; action?: React.ReactNode; className?: string; children: React.ReactNode }) {
  return (
    <motion.div variants={rise} className={className}>
      <Card className="flex h-full flex-col">
        <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>{title}</CardTitle>
            {description && <CardDescription className="mt-1">{description}</CardDescription>}
          </div>
          {action}
        </CardHeader>
        <CardContent className="flex-1">{children}</CardContent>
      </Card>
    </motion.div>
  )
}

const ChartSkeleton = ({ h = 260 }: { h?: number }) => <Skeleton className="w-full" style={{ height: h }} />
const Empty = ({ children }: { children: React.ReactNode }) => <p className="grid h-56 place-items-center text-center text-sm text-muted-foreground">{children}</p>

function AttentionRow({ item }: { item: AttentionItem }) {
  const link = attentionHref(item.view)
  const sev = SEVERITY[item.severity] ?? SEVERITY.notice
  const body = (
    <div className="flex items-start gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-accent">
      <Badge tone={sev.tone} className="mt-0.5 shrink-0">
        {sev.word}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] font-medium leading-snug">{item.title}</p>
        <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{item.detail}</p>
      </div>
      {item.value > 0 && <span className="tabular shrink-0 text-[13px] font-semibold">{compactINR(item.value)}</span>}
      <ArrowUpRight className="mt-1 size-3.5 shrink-0 text-subtle" />
    </div>
  )
  return link.external ? <a href={link.to}>{body}</a> : <Link to={link.to}>{body}</Link>
}

export default function DashboardPage() {
  const { user, can } = useSession()
  const money = can('bills.view_all')
  const reports = can('reports.view')

  const inbox = useInbox()
  const attention = useAttention()
  const receivables = useReceivables(money)
  const payables = usePayables(money)
  const retention = useRetention(money)
  const pnl = useProjectPnl(reports)
  const cash = useCashFlow(money)

  const first = user?.name?.split(' ')[0]
  const waiting = inbox.data?.mine ?? 0
  const today = new Intl.DateTimeFormat('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(new Date())
  const items = attention.data?.items ?? []
  const cashHasData = (cash.data ?? []).some((m) => m.received || m.paid)

  const fig = (n: number | undefined, loading: boolean) => (loading ? undefined : <Figure value={n ?? 0} format={compactINR} />)
  const looks = attention.data?.summary.items

  return (
    <>
      <PageHeader
        eyebrow="Command Center"
        title={first ? `${greeting()}, ${first}` : 'Welcome to Y ERP'}
        description={`${today}. ${looks === undefined ? '' : looks ? `${looks} thing${looks === 1 ? '' : 's'} worth a look.` : 'Nothing needs you right now.'}`}
        actions={
          <>
            <Button variant={waiting ? 'primary' : 'outline'} asChild>
              <Link to="/approvals">
                <CheckCheck /> {waiting ? `${waiting} waiting on you` : 'Approvals'}
              </Link>
            </Button>
          </>
        }
      />

      <motion.div variants={stagger} initial="hidden" animate="show" className="grid gap-5 lg:grid-cols-3">
        {(money || reports) && (
          <motion.div variants={rise} className="grid grid-cols-2 gap-3 lg:col-span-3 lg:grid-cols-5">
            {money && (
              <>
                <Stat label="Owed to us" value={fig(receivables.data?.summary.owed, receivables.isPending)} loading={receivables.isPending} tone={receivables.data?.summary.overdue ? 'warning' : undefined} sub={receivables.data ? `${compactINR(receivables.data.summary.overdue)} overdue` : undefined} />
                <Stat label="We owe" value={fig(payables.data?.summary.owed, payables.isPending)} loading={payables.isPending} sub={payables.data ? `${compactINR(payables.data.summary.overdue)} overdue` : undefined} />
                <Stat label="Retention held" value={fig(retention.data?.summary.held, retention.isPending)} loading={retention.isPending} sub={retention.data ? `${compactINR(retention.data.summary.on_finished_jobs)} on finished jobs` : undefined} />
              </>
            )}
            {reports && (
              <>
                <Stat label="Order book" value={fig(pnl.data?.summary.order_value, pnl.isPending)} loading={pnl.isPending} sub={pnl.data ? `${compactINR(pnl.data.summary.revenue)} earned` : undefined} />
                <Stat
                  label="Margin to date"
                  value={fig(pnl.data?.summary.margin, pnl.isPending)}
                  loading={pnl.isPending}
                  tone={pnl.data && pnl.data.summary.margin < 0 ? 'danger' : 'success'}
                  sub={pnl.data ? (pnl.data.summary.losing_money ? `${pnl.data.summary.losing_money} project${pnl.data.summary.losing_money === 1 ? '' : 's'} losing money` : 'No project is losing money') : undefined}
                />
              </>
            )}
          </motion.div>
        )}

        {reports && (
          <Panel title="Project profitability" description="Revenue earned against cost incurred, biggest projects first." className="lg:col-span-2">
            {pnl.isPending ? (
              <ChartSkeleton h={300} />
            ) : pnl.isError ? (
              <Empty>Could not load the projects.</Empty>
            ) : pnl.data.projects.length === 0 ? (
              <Empty>No projects yet.</Empty>
            ) : (
              <Suspense fallback={<ChartSkeleton h={300} />}>
                <ProfitChart projects={pnl.data.projects} />
              </Suspense>
            )}
          </Panel>
        )}

        <Panel
          title="What needs you"
          description={attention.data ? `${formatINR(attention.data.summary.money_at_stake)} at stake` : undefined}
          className={reports ? '' : 'lg:col-span-3'}
          action={
            attention.data && attention.data.summary.looks_wrong > 0 ? (
              <Badge tone="danger">
                <AlertTriangle className="size-3" /> {attention.data.summary.looks_wrong} wrong
              </Badge>
            ) : undefined
          }
        >
          {attention.isPending ? (
            <div className="space-y-3">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : attention.isError ? (
            <Empty>Could not load this.</Empty>
          ) : items.length === 0 ? (
            <Empty>Nothing needs you. Everything that needed a decision has had one.</Empty>
          ) : (
            <ul className="-mx-2 space-y-0.5">
              {items.slice(0, 7).map((i) => (
                <li key={i.kind + i.title}>
                  <AttentionRow item={i} />
                </li>
              ))}
              {items.length > 7 && <li className="px-2 pt-2 text-xs text-muted-foreground">and {items.length - 7} more in the current app</li>}
            </ul>
          )}
        </Panel>

        {money && (
          <>
            <Panel title="Cash flow" description="Money received and paid out each month, and the running balance." className="lg:col-span-2">
              {cash.isPending ? (
                <ChartSkeleton h={300} />
              ) : cash.isError ? (
                <Empty>Could not load the ledger.</Empty>
              ) : !cashHasData ? (
                <Empty>Nothing received or paid in the last twelve months.</Empty>
              ) : (
                <Suspense fallback={<ChartSkeleton h={300} />}>
                  <CashFlowChart months={cash.data} />
                </Suspense>
              )}
            </Panel>
            <Panel title="Owed, by age" description="What is owed to us, and what we owe, by how long it has been outstanding.">
              {receivables.isPending || payables.isPending ? (
                <ChartSkeleton />
              ) : receivables.isError && payables.isError ? (
                <Empty>Could not load this.</Empty>
              ) : (
                <Suspense fallback={<ChartSkeleton />}>
                  <AgeingChart receivable={receivables.data?.buckets} payable={payables.data?.buckets} />
                </Suspense>
              )}
            </Panel>
          </>
        )}
      </motion.div>
    </>
  )
}
