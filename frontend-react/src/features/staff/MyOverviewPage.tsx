import { Link } from 'react-router-dom'
import { AlertTriangle, CalendarDays, FileText, Receipt, ShoppingCart, Wallet } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Skeleton, Stat, StatGrid } from '@/components/ui'
import { useMyDashboard, useToday } from '@/api/staff'
import { formatDate, plural } from '@/lib/format'
import { useSession } from '@/lib/session'
import { ClockCard } from './ClockCard'

const QUICK = [
  { to: '/me/costs', label: 'Raise a cost', hint: 'A bill or receipt for approval', icon: Receipt, perm: 'bills.submit' },
  { to: '/me/orders', label: 'Raise an order', hint: 'Get spend agreed first', icon: ShoppingCart, perm: 'bills.submit' },
  { to: '/me/leave', label: 'Ask for leave', hint: 'Balance and requests', icon: CalendarDays },
  { to: '/me/payslips', label: 'Payslips', hint: 'Your last six', icon: Wallet },
  { to: '/me/documents', label: 'Documents', hint: 'What HR has asked for', icon: FileText },
]

/** A member of staff's own day: the clock, the sites they work on, what is waiting for them. */
export default function MyOverviewPage() {
  const { user, can } = useSession()
  const today = useToday()
  const dash = useMyDashboard()
  const first = (today.data?.name || user?.name || '').split(' ')[0]
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const s = dash.data?.attendance_summary

  return (
    <>
      <PageHeader eyebrow={user?.department || 'My work'} title={first ? `${greeting}, ${first}` : greeting} description={today.data ? formatDate(today.data.date) : undefined} />
      <ClockCard />
      <StatGrid className="mt-6">
        <Stat label="Days present (30 days)" value={s?.days_present ?? 0} loading={dash.isPending} />
        <Stat label="Hours worked" value={s?.total_hours ?? 0} loading={dash.isPending} />
        <Stat label="Average a day" value={s?.avg_hours ?? 0} sub="hours" loading={dash.isPending} />
        <Stat label="Sites you work on" value={today.data?.sites.length ?? 0} loading={today.isPending} />
      </StatGrid>

      {(today.data?.waiting?.length ?? 0) > 0 && (
        <section aria-label="Waiting for you" className="mb-6 rounded-xl border border-warning/40 bg-warning/5 p-4">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold"><AlertTriangle className="size-4 text-warning" /> Waiting for you</h2>
          <ul className="grid gap-1.5 text-sm">{today.data?.waiting?.map((w, i) => <li key={i}>{w.text}</li>)}</ul>
        </section>
      )}

      <h2 className="mb-3 text-sm font-semibold">Quick actions</h2>
      <div className="mb-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {QUICK.filter((a) => !a.perm || can(a.perm)).map(({ to, label, hint, icon: Icon }) => (
          <Link key={to} to={to} className="flex items-center gap-3 rounded-xl border border-border bg-card p-4 shadow-card transition-colors hover:bg-accent">
            <span className="grid size-10 place-items-center rounded-lg bg-primary-soft text-primary"><Icon className="size-5" /></span>
            <span><span className="block text-sm font-medium">{label}</span><span className="block text-xs text-muted-foreground">{hint}</span></span>
          </Link>
        ))}
      </div>

      <h2 className="mb-3 text-sm font-semibold">Your sites</h2>
      {today.isPending ? <Skeleton className="h-24 w-full" /> : today.data?.sites.length ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {today.data.sites.map((j) => (
            <section key={j.job_id} aria-label={j.name} className="rounded-xl border border-border bg-card p-4 shadow-card">
              <p className="text-xs text-muted-foreground">{j.number}</p>
              <h3 className="font-semibold">{j.name}</h3>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge tone={j.diary ? 'success' : 'neutral'}>{j.diary ? `Diary ${j.diary.status.toLowerCase()}` : 'No diary today'}</Badge>
                {j.permits_live > 0 && <Badge tone={j.permits_overdue ? 'danger' : 'info'}>{plural(j.permits_live, 'permit')} live</Badge>}
                {j.incidents_open > 0 && <Badge tone="danger">{plural(j.incidents_open, 'open incident')}</Badge>}
                {j.inspections_open > 0 && <Badge tone="warning">{plural(j.inspections_open, 'inspection')} due</Badge>}
                {j.unread > 0 && <Badge tone="info">{j.unread} unread</Badge>}
              </div>
            </section>
          ))}
        </div>
      ) : <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No sites are assigned to you yet. Your manager assigns them.</p>}
    </>
  )
}
