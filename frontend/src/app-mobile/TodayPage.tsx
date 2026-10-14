import { Link, Navigate } from 'react-router-dom'
import { Bell, BookOpen, ChevronRight, ListChecks, PackageCheck, Ruler, ShieldAlert, type LucideIcon } from 'lucide-react'
import { useInbox } from '@/api/approvals'
import { attentionHref, useAttention } from '@/api/dashboard'
import { useDayPlan } from '@/api/schedule'
import { useIdentity } from '@/api/identity'
import { CompanyMark } from '@/components/company/CompanyMark'
import { Skeleton } from '@/components/ui'
import { today } from '@/lib/format'
import { useSession } from '@/lib/session'
import { cn, compactINR } from '@/lib/utils'
import { useCurrentSite, useSite } from './site'
import { Label, LargeTitle, Pill, Sheet } from './ui'

const greeting = () => {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

function Ring({ percent }: { percent: number }) {
  const p = Math.max(0, Math.min(100, Math.round(percent)))
  return (
    <div className="relative size-24 shrink-0">
      <svg viewBox="0 0 36 36" className="size-24 -rotate-90" aria-hidden>
        <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="4" className="stroke-foreground/10" />
        <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="4" strokeLinecap="round" className="stroke-primary" strokeDasharray={`${(p / 100) * 97.4} 97.4`} />
      </svg>
      <span className="absolute inset-0 grid place-items-center font-display text-2xl font-bold">{p}%</span>
    </div>
  )
}

const QUICK: { label: string; path: string; perm?: string; icon: LucideIcon; tone: string }[] = [
  { label: 'Diary', path: '/projects/diary', perm: 'site.record', icon: BookOpen, tone: 'bg-primary/15 text-primary' },
  { label: 'Tasks', path: '/projects/programme', icon: ListChecks, tone: 'bg-success/15 text-success' },
  { label: 'Measure', path: '/subcontractors/measurement-book', perm: 'site.record', icon: Ruler, tone: 'bg-primary/15 text-primary' },
  { label: 'Goods in', path: '/store/goods-receipt', perm: 'stores.receive', icon: PackageCheck, tone: 'bg-warning/15 text-warning' },
  { label: 'Safety', path: '/projects/safety', icon: ShieldAlert, tone: 'bg-danger/15 text-danger' },
]

/** The phone app's front page: the site you are on, how today is going, and only what needs you. */
export default function TodayPage() {
  const { user, can, isLoading } = useSession()
  const identity = useIdentity()
  const { site, sites: list, isPending: loadingSites } = useCurrentSite()
  const set = useSite((s) => s.set)
  const plan = useDayPlan(site?.id ?? 0, today())
  const attention = useAttention()
  const inbox = useInbox()
  if (isLoading) return <Skeleton className="mt-4 h-64 w-full rounded-3xl" />
  if (user?.headOffice) return <Navigate to="/ho" replace />

  const tasks = plan.data?.tasks ?? []
  const done = tasks.filter((t) => t.done).length
  const percent = tasks.length ? (done / tasks.length) * 100 : (plan.data?.summary.done_percent ?? 0)
  const variance = plan.data?.summary.variance ?? 0
  const items = (attention.data?.items ?? []).slice(0, 3)
  const waiting = inbox.data?.mine ?? 0
  const quick = QUICK.filter((q) => !q.perm || can(q.perm))

  return (
    <div className="pb-4">
      <div className="flex items-center justify-between gap-3 pt-1">
        <div className="flex min-w-0 items-center gap-3">
          <CompanyMark className="size-10 rounded-xl" />
          <div className="min-w-0 leading-tight">
            <div className="text-xs text-muted-foreground">{greeting()}, {user?.name?.split(' ')[0] ?? ''}</div>
            <div className="truncate text-[15px] font-semibold">{identity.data?.name || user?.company || 'Y ERP'}</div>
          </div>
        </div>
        <Link to="/approvals" aria-label="Approvals waiting" className="relative grid size-10 place-items-center rounded-full bg-card">
          <Bell className="size-5" />
          {waiting > 0 && <span className="absolute right-2 top-2 size-2 rounded-full bg-primary ring-2 ring-card" />}
        </Link>
      </div>

      <LargeTitle title="Today" sub={new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })} />

      {loadingSites ? <Skeleton className="h-9 w-2/3 rounded-full" /> : list.length > 0 && (
        <div role="tablist" aria-label="Site" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {list.map((p) => (
            <button key={p.id} role="tab" aria-selected={p.id === site?.id} type="button" onClick={() => set(p.id)}
              className={cn('h-9 shrink-0 rounded-full px-4 text-sm font-medium', p.id === site?.id ? 'bg-primary text-primary-foreground' : 'bg-card text-foreground')}>
              {p.name}
            </button>
          ))}
        </div>
      )}

      {site && (
        <Link to={`/projects/programme?job=${site.id}`} className="mt-4 flex items-center gap-4 rounded-[26px] border border-border bg-gradient-to-br from-primary/25 via-card to-card p-4">
          {plan.isPending ? <Skeleton className="size-24 rounded-full" /> : <Ring percent={percent} />}
          <div className="min-w-0">
            <div className="text-[17px] font-semibold">{tasks.length ? `${done} of ${tasks.length} tasks done` : 'Work done so far'}</div>
            <p className="mt-1 text-[13px] leading-snug text-muted-foreground">{site.number ? `${site.number} · ` : ''}{site.name}</p>
            {plan.data && <div className="mt-2.5"><Pill tone={variance < -5 ? 'bad' : variance < 0 ? 'warn' : 'ok'}>{variance === 0 ? 'On plan' : `${Math.abs(variance)} pts ${variance < 0 ? 'behind' : 'ahead of'} plan`}</Pill></div>}
          </div>
        </Link>
      )}

      {quick.length > 0 && (
        <>
          <Label>Quick actions</Label>
          <div className="grid grid-cols-5 gap-2">
            {quick.map(({ label, path, icon: Icon, tone }) => (
              <Link key={label} to={path} className="flex h-[84px] flex-col items-center justify-center gap-2 rounded-2xl border border-border bg-card text-[11.5px] font-medium active:scale-95">
                <span className={cn('grid size-9 place-items-center rounded-xl', tone)}><Icon className="size-[18px]" /></span>{label}
              </Link>
            ))}
          </div>
        </>
      )}

      <Label action={<Link to="/approvals" className="text-sm font-medium text-primary">See all</Link>}>Needs you</Label>
      <Sheet className="divide-y divide-border py-1">
        {waiting > 0 && (
          <Link to="/approvals" className="flex items-center gap-3 py-3">
            <span className="grid size-10 place-items-center rounded-xl bg-primary/15 font-display text-lg font-bold text-primary">{waiting}</span>
            <span className="min-w-0 flex-1"><b className="block text-[15px]">{waiting === 1 ? '1 approval waiting' : `${waiting} approvals waiting`}</b><span className="text-[13px] text-muted-foreground">Clear them in a few taps</span></span>
            <ChevronRight className="size-4 text-muted-foreground" />
          </Link>
        )}
        {items.map((it) => (
          <Link key={it.kind + it.title} to={attentionHref(it.view).external ? '/approvals' : attentionHref(it.view).to} className="flex items-center gap-3 py-3">
            <span className="min-w-0 flex-1"><b className="block truncate text-[15px]">{it.title}</b><span className="block truncate text-[13px] text-muted-foreground">{it.detail}</span></span>
            {it.value > 0 && <span className="text-[15px] font-semibold">{compactINR(it.value)}</span>}
            <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
          </Link>
        ))}
        {waiting === 0 && items.length === 0 && (attention.isPending ? <Skeleton className="my-3 h-12 w-full" /> : <p className="py-4 text-center text-sm text-muted-foreground">{attention.isError ? 'Could not load this. Pull down or reopen the app to try again.' : 'Nothing needs you right now.'}</p>)}
      </Sheet>
    </div>
  )
}
