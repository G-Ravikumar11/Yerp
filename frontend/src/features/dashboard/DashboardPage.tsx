import { lazy, Suspense, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { AlertTriangle, ArrowUpRight, CheckCheck } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Select, Skeleton, Stat } from '@/components/ui'
import { useInbox } from '@/api/approvals'
import { attentionHref, useAttention, useCashFlow, usePayables, useProjectPnl, useReceivables, useRetention, type AttentionItem } from '@/api/dashboard'
import { Figure } from './Figure'
import { useCosts } from '@/api/costs'
import { useSafety } from '@/api/safety'
import { useSession } from '@/lib/session'
import { cn, compactINR, formatINR } from '@/lib/utils'

// The chart library is the heaviest thing on this page, and the tiles above it should not wait for it.
const ProfitChart = lazy(() => import('./Charts').then((m) => ({ default: m.ProfitChart })))
const CashFlowChart = lazy(() => import('./Charts').then((m) => ({ default: m.CashFlowChart })))
const AgeingChart = lazy(() => import('./Charts').then((m) => ({ default: m.AgeingChart })))
const MarginChart = lazy(() => import('./Charts').then((m) => ({ default: m.MarginChart })))
const BudgetChart = lazy(() => import('./Charts').then((m) => ({ default: m.BudgetChart })))
const CostMixChart = lazy(() => import('./Charts').then((m) => ({ default: m.CostMixChart })))
const IncidentsChart = lazy(() => import('./Charts').then((m) => ({ default: m.IncidentsChart })))


type View = 'profit' | 'budget' | 'cost' | 'margin' | 'cash' | 'ageing' | 'safety'
const VIEWS: { value: View; label: string; hint: string; needs: 'reports' | 'money' | 'any' }[] = [
  { value: 'profit', label: 'Money earned vs spent', hint: 'For each project: how much money it has brought in, and how much it has cost. Biggest projects first.', needs: 'reports' },
  { value: 'budget', label: 'Planned vs actual cost', hint: 'For each project: the contract amount, what we expect it to cost, and what we have spent so far.', needs: 'reports' },
  { value: 'cost', label: 'Where our money goes', hint: 'How the money we spend is split between materials, labour, contractors and the rest.', needs: 'reports' },
  { value: 'margin', label: 'Profit or loss per project', hint: 'Green bars are projects making money. Red bars are projects losing money.', needs: 'reports' },
  { value: 'cash', label: 'Money in and out', hint: 'Money received and money paid out each month, and the balance left.', needs: 'money' },
  { value: 'ageing', label: 'Unpaid money, by how old', hint: 'Money we are waiting to receive and money we still have to pay, grouped by how long it has been pending.', needs: 'money' },
  { value: 'safety', label: 'Safety incidents', hint: 'How many incidents and near misses have been reported, and of what kind.', needs: 'any' },
]
const VIEW_KEY = 'yerp-dashboard-chart'
const savedView = (): View => {
  try {
    const v = localStorage.getItem(VIEW_KEY)
    return VIEWS.some((x) => x.value === v) ? (v as View) : 'profit'
  } catch {
    return 'profit'
  }
}

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
function Panel({ id, title, description, action, className, children }: { id?: string; title: string; description?: string; action?: React.ReactNode; className?: string; children: React.ReactNode }) {
  return (
    <motion.div id={id} variants={rise} className={cn('scroll-mt-24', className)}>
      <Card className="flex h-full flex-col transition-shadow duration-500">
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
const Empty = ({ children }: { children: React.ReactNode }) => <p className="grid h-40 place-items-center text-center text-sm text-muted-foreground">{children}</p>

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

  const costs = useCosts(reports)
  const safety = useSafety(0)

  const first = user?.name?.split(' ')[0]
  const waiting = inbox.data?.mine ?? 0
  const today = new Intl.DateTimeFormat('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(new Date())
  const items = attention.data?.items ?? []
  const cashHasData = (cash.data ?? []).some((m) => m.received || m.paid)

  const [pickedView, setView] = useState<View>(savedView)
  const available = VIEWS.filter((v) => (v.needs === 'reports' ? reports : v.needs === 'money' ? money : true))
  const view = available.some((v) => v.value === pickedView) ? pickedView : (available[0]?.value ?? 'profit')
  const pickView = (v: View) => {
    setView(v)
    try {
      localStorage.setItem(VIEW_KEY, v)
    } catch {
      /* private window: the choice just lasts until the page is closed */
    }
  }

  const fallback = <ChartSkeleton h={210} />
  let chart: React.ReactNode = null
  if (view === 'profit') {
    chart = pnl.isPending ? fallback : pnl.isError ? <Empty>Could not load the projects.</Empty> : pnl.data.projects.length === 0 ? <Empty>No projects yet.</Empty> : <Suspense fallback={fallback}><ProfitChart projects={pnl.data.projects} /></Suspense>
  } else if (view === 'margin') {
    chart = pnl.isPending ? fallback : pnl.isError || pnl.data.projects.length === 0 ? <Empty>No projects to show.</Empty> : <Suspense fallback={fallback}><MarginChart projects={pnl.data.projects} /></Suspense>
  } else if (view === 'budget') {
    chart = costs.isPending ? fallback : costs.isError ? <Empty>Could not load the costs.</Empty> : costs.data.projects.length === 0 ? <Empty>No projects yet.</Empty> : <Suspense fallback={fallback}><BudgetChart projects={costs.data.projects} /></Suspense>
  } else if (view === 'cost') {
    chart = costs.isPending ? fallback : costs.isError ? <Empty>Could not load this.</Empty> : !costs.data.summary.categories.some((c) => c.amount > 0) ? <Empty>No cost has been booked yet.</Empty> : <Suspense fallback={fallback}><CostMixChart categories={costs.data.summary.categories} /></Suspense>
  } else if (view === 'safety') {
    const counts = new Map<string, number>()
    for (const i of safety.data?.incidents ?? []) counts.set(i.kind, (counts.get(i.kind) ?? 0) + 1)
    const kinds = [...counts].map(([kind, count]) => ({ kind, count }))
    chart = safety.isPending ? fallback : safety.isError ? <Empty>Could not load the incidents.</Empty> : kinds.length === 0 ? <Empty>No incident has been reported. Every day so far has been a safe one.</Empty> : <Suspense fallback={fallback}><IncidentsChart kinds={kinds} /></Suspense>
  } else if (view === 'cash') {
    chart = cash.isPending ? fallback : cash.isError ? <Empty>Could not load the ledger.</Empty> : !cashHasData ? <Empty>Nothing received or paid in the last twelve months.</Empty> : <Suspense fallback={fallback}><CashFlowChart months={cash.data} /></Suspense>
  } else {
    chart = receivables.isPending || payables.isPending ? fallback : receivables.isError && payables.isError ? <Empty>Could not load this.</Empty> : <Suspense fallback={fallback}><AgeingChart receivable={receivables.data?.buckets} payable={payables.data?.buckets} /></Suspense>
  }

  // "4 things worth a look" takes the person to the list of them, and makes it glow for a moment so the eye finds it.
  const showAttention = () => {
    const panel = document.getElementById('what-needs-you')
    if (!panel) return
    panel.scrollIntoView({ behavior: 'smooth', block: 'center' })
    const card = panel.firstElementChild as HTMLElement | null
    card?.classList.add('ring-2', 'ring-primary', 'shadow-lift')
    window.setTimeout(() => card?.classList.remove('ring-2', 'ring-primary', 'shadow-lift'), 1800)
  }

  const fig = (n: number | undefined, loading: boolean) => (loading ? undefined : <Figure value={n ?? 0} format={compactINR} />)
  const looks = attention.data?.summary.items

  return (
    <>
      <PageHeader
        eyebrow="Command Center"
        title={first ? `${greeting()}, ${first}` : 'Welcome to Y ERP'}
        description={
          <>
            {today}.{' '}
            {looks === undefined ? null : looks ? (
              <button type="button" onClick={showAttention} className="font-medium text-primary underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-none">
                {looks} thing{looks === 1 ? '' : 's'} worth a look →
              </button>
            ) : (
              'Nothing needs you right now.'
            )}
          </>
        }
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
        <motion.div variants={rise} className="grid grid-cols-2 gap-3 lg:col-span-3 lg:grid-cols-3 xl:grid-cols-6">
            {money && (
              <>
                <Stat label="Money to receive" to="/money/owed?tab=owed" value={fig(receivables.data?.summary.owed, receivables.isPending)} loading={receivables.isPending} tone={receivables.data?.summary.overdue ? 'warning' : undefined} sub={receivables.data ? `${compactINR(receivables.data.summary.overdue)} overdue from clients` : undefined} />
                <Stat label="Money to pay" to="/money/owed?tab=owe" value={fig(payables.data?.summary.owed, payables.isPending)} loading={payables.isPending} sub={payables.data ? `${compactINR(payables.data.summary.overdue)} overdue to suppliers` : undefined} />
                <Stat label="Retention money held" to="/money/owed?tab=retention" value={fig(retention.data?.summary.held, retention.isPending)} loading={retention.isPending} sub={retention.data ? `${compactINR(retention.data.summary.on_finished_jobs)} on completed projects` : undefined} />
              </>
            )}
            {reports && (
              <>
                <Stat label="Total contract value" to="/clients/work-orders" value={fig(pnl.data?.summary.order_value, pnl.isPending)} loading={pnl.isPending} sub={pnl.data ? `${compactINR(pnl.data.summary.revenue)} earned so far` : undefined} />
                <Stat
                  label="Profit so far"
                  to="/projects/profit"
                  value={fig(pnl.data?.summary.margin, pnl.isPending)}
                  loading={pnl.isPending}
                  tone={pnl.data && pnl.data.summary.margin < 0 ? 'danger' : 'success'}
                  sub={pnl.data ? (pnl.data.summary.losing_money ? `${pnl.data.summary.losing_money} project${pnl.data.summary.losing_money === 1 ? '' : 's'} losing money` : 'No project is losing money') : undefined}
                />
              </>
            )}
            <Stat
              label="Safety incidents"
              to="/projects/safety"
              value={safety.data ? safety.data.incidents.length : 0}
              loading={safety.isPending}
              tone={safety.data?.summary.open ? 'warning' : undefined}
              sub={safety.data ? `${safety.data.summary.open} open, ${safety.data.summary.incidents_this_month} this month` : undefined}
            />
          </motion.div>

        <Panel
          title="How the business is doing"
          description={VIEWS.find((v) => v.value === view)?.hint}
          className="lg:col-span-2"
          action={<Select aria-label="Chart" className="h-9 w-56" value={view} onChange={(e) => pickView(e.target.value as View)} options={available} />}
        >
          {chart}
        </Panel>

        <Panel
          id="what-needs-you"
          title="What needs you"
          description={attention.data ? `${formatINR(attention.data.summary.money_at_stake)} at stake` : undefined}
          className=""
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


      </motion.div>
    </>
  )
}
