import { Link, Navigate } from 'react-router-dom'
import { Bell, BookOpen, ChevronRight, FileCheck2, Grid2x2, ListChecks, PackageCheck, Ruler, ShieldAlert, type LucideIcon } from 'lucide-react'
import { useInbox } from '@/api/approvals'
import { attentionHref, useAttention } from '@/api/dashboard'
import { useDayPlan } from '@/api/schedule'
import { Skeleton } from '@/components/ui'
import { today } from '@/lib/format'
import { initials, useSession } from '@/lib/session'
import { cn, compactINR } from '@/lib/utils'
import { useCurrentSite, useSite } from './site'
import { Label, Pill, roundBtn, Sheet } from './ui'

const greeting = () => {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

/** A site's two letters for its circle: the first letters of its first two words, or the first two of a single word. */
const letters = (name: string) => {
  const w = name.trim().split(/\s+/).filter(Boolean)
  return ((w.length > 1 ? w[0][0] + w[1][0] : (w[0] ?? '?').slice(0, 2)) || '?').toUpperCase()
}
const COLOURS = ['#2563eb', '#7c3aed', '#0891b2', '#059669', '#d97706', '#db2777']

function Ring({ percent }: { percent: number }) {
  const p = Math.max(0, Math.min(100, Math.round(percent)))
  return (
    <div className="relative size-[72px] shrink-0">
      <svg viewBox="0 0 36 36" className="size-[72px] -rotate-90" aria-hidden>
        <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="4" className="stroke-foreground/10" />
        <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="4" strokeLinecap="round" className="stroke-primary" strokeDasharray={`${(p / 100) * 97.4} 97.4`} />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-lg font-extrabold">{p}%</span>
    </div>
  )
}

const QUICK: { label: string; path: string; perm?: string; icon: LucideIcon; from: string; to: string }[] = [
  { label: 'Diary', path: '/projects/diary', perm: 'site.record', icon: BookOpen, from: '#8b5cf6', to: '#a78bfa' },
  { label: 'Tasks', path: '/projects/programme', icon: ListChecks, from: '#10b981', to: '#34d399' },
  { label: 'Measure', path: '/subcontractors/measurement-book', perm: 'site.record', icon: Ruler, from: '#0ea5e9', to: '#38bdf8' },
  { label: 'Goods in', path: '/store/hub/inward/grn/new', perm: 'store.inward.create', icon: PackageCheck, from: '#f59e0b', to: '#fbbf24' },
  { label: 'Safety', path: '/projects/safety', icon: ShieldAlert, from: '#ef4444', to: '#f87171' },
]

/** One figure on the blue card. */
function Figure({ big, label }: { big: string | number; label: string }) {
  return (
    <div>
      <b className="block text-[26px] font-extrabold leading-none tracking-tight">{big}</b>
      <span className="mt-1 block text-xs opacity-90">{label}</span>
    </div>
  )
}

/** The phone app's front page: today at a glance, the sites you work on, and only what needs you. */
export default function TodayPage() {
  const { user, can, isLoading } = useSession()
  const { site, sites: list, isPending: loadingSites } = useCurrentSite()
  const set = useSite((s) => s.set)
  const plan = useDayPlan(site?.id ?? 0, today())
  const attention = useAttention()
  const inbox = useInbox()
  if (isLoading) return <Skeleton className="mt-4 h-64 w-full rounded-2xl" />
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
      <div className="flex items-center gap-3 pb-3.5 pt-1">
        <span className="grid size-11 shrink-0 place-items-center rounded-full bg-[image:var(--app-grad)] text-[15px] font-bold text-white">{initials(user?.name)}</span>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="text-[12.5px] text-muted-foreground">{greeting()}</div>
          <div className="truncate text-xl font-bold tracking-tight">{user?.name?.split(' ')[0] ?? ''}</div>
        </div>
        <Link to="/approvals" aria-label={waiting > 0 ? `${waiting} approvals waiting` : 'Approvals'} className={cn(roundBtn, 'relative')}>
          <Bell className="size-5" />
          {waiting > 0 && <span className="absolute right-2.5 top-2.5 size-2.5 rounded-full bg-danger ring-2 ring-card" />}
        </Link>
      </div>

      {/* Today at a glance. */}
      <div className="relative overflow-hidden rounded-[26px] bg-[image:var(--app-grad)] p-4 text-white">
        <span className="pointer-events-none absolute -right-10 -top-16 size-44 rounded-full bg-white/10" aria-hidden />
        <span className="pointer-events-none absolute -bottom-16 right-12 size-36 rounded-full bg-white/[0.07]" aria-hidden />
        <div className="relative flex justify-between text-[12.5px] opacity-95">
          <span>{new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })}</span>
          <span>{list.length} {list.length === 1 ? 'site' : 'sites'} live</span>
        </div>
        <div className="relative mt-3.5 grid grid-cols-3">
          <Figure big={tasks.length ? `${done}/${tasks.length}` : `${Math.round(percent)}%`} label={tasks.length ? 'tasks done' : 'work done'} />
          <Figure big={list.length} label="sites active" />
          <Figure big={waiting} label="to approve" />
        </div>
      </div>

      {/* Your sites, as circles: the open one has the blue ring. */}
      <Label action={<Link to="/projects" className="text-sm font-semibold text-primary">See all</Link>}>Your sites</Label>
      {loadingSites ? <Skeleton className="h-20 w-2/3 rounded-full" /> : (
        <div role="tablist" aria-label="Site" className="-mx-4 flex gap-3.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {list.map((p, i) => {
            const on = p.id === site?.id
            return (
              <button key={p.id} role="tab" aria-selected={on} type="button" onClick={() => set(p.id)} className="w-16 shrink-0 text-center active:scale-95">
                <span className="block size-16 rounded-full p-[3px]" style={{ background: on ? 'conic-gradient(var(--primary), #7dd3fc, var(--primary))' : 'var(--border)' }}>
                  <span className="grid size-full place-items-center rounded-full border-[3px] border-background text-base font-bold text-white" style={{ background: COLOURS[i % COLOURS.length] }}>{letters(p.name)}</span>
                </span>
                <span className={cn('mt-1.5 block truncate text-[11.5px]', on ? 'font-semibold text-foreground' : 'text-muted-foreground')}>{p.name}</span>
              </button>
            )
          })}
          <Link to="/projects" className="w-16 shrink-0 text-center active:scale-95" aria-label="All projects">
            <span className="grid size-16 place-items-center rounded-full border-2 border-dashed border-primary text-primary"><Grid2x2 className="size-6" /></span>
            <span className="mt-1.5 block text-[11.5px] text-muted-foreground">All</span>
          </Link>
        </div>
      )}

      {site && (
        <Link to={`/projects/programme?job=${site.id}`} className="mt-4 block active:scale-[0.99]">
          <Sheet className="flex items-center gap-4">
            {plan.isPending ? <Skeleton className="size-[72px] rounded-full" /> : <Ring percent={percent} />}
            <div className="min-w-0 flex-1">
              <div className="text-[17px] font-bold tracking-tight">{tasks.length ? `${done} of ${tasks.length} tasks done` : 'Work done so far'}</div>
              <p className="mt-0.5 truncate text-[13px] text-muted-foreground">{site.number ? `${site.number} · ` : ''}{site.name}</p>
              {plan.data && <div className="mt-2"><Pill tone={variance < -5 ? 'bad' : variance < 0 ? 'warn' : 'ok'}>{variance === 0 ? 'On plan' : `${Math.abs(variance)} pts ${variance < 0 ? 'behind' : 'ahead of'} plan`}</Pill></div>}
            </div>
            <ChevronRight className="size-5 shrink-0 text-muted-foreground" />
          </Sheet>
        </Link>
      )}

      {quick.length > 0 && (
        <>
          <Label>Quick actions</Label>
          <div className="grid grid-cols-5 gap-2 text-center">
            {quick.map(({ label, path, icon: Icon, from, to }) => (
              <Link key={label} to={path} className="active:scale-95">
                <span className="mx-auto grid size-[54px] place-items-center rounded-[18px] text-white shadow-[var(--app-card-shadow)]" style={{ background: `linear-gradient(135deg, ${from}, ${to})` }}><Icon className="size-[22px]" /></span>
                <span className="mt-1.5 block text-[11.5px] font-semibold text-muted-foreground">{label}</span>
              </Link>
            ))}
          </div>
        </>
      )}

      <Label action={<Link to="/approvals" className="text-sm font-semibold text-primary">See all</Link>}>
        Needs you
        {waiting > 0 && <span className="rounded-full bg-primary px-2 py-0.5 text-[11px] font-bold text-primary-foreground">{waiting}</span>}
      </Label>
      <div className="space-y-2.5">
        {waiting > 0 && (
          <Sheet>
            <div className="flex items-center gap-3">
              <span className="grid size-11 shrink-0 place-items-center rounded-[14px] bg-primary/15 text-primary"><FileCheck2 className="size-5" /></span>
              <span className="min-w-0 flex-1"><b className="block text-[15px] font-semibold">{waiting === 1 ? '1 approval waiting' : `${waiting} approvals waiting`}</b><span className="text-[12.5px] text-muted-foreground">Clear them so work and payments can move</span></span>
            </div>
            <Link to="/approvals" className="mt-3 block rounded-[14px] bg-[image:var(--app-grad)] py-2.5 text-center text-sm font-semibold text-white active:opacity-90">Review</Link>
          </Sheet>
        )}
        {items.map((it) => (
          <Link key={it.kind + it.title} to={attentionHref(it.view).external ? '/approvals' : attentionHref(it.view).to} className="block active:scale-[0.99]">
            <Sheet className="flex items-center gap-3">
              <span className="min-w-0 flex-1"><b className="block truncate text-[15px] font-semibold">{it.title}</b><span className="block truncate text-[12.5px] text-muted-foreground">{it.detail}</span></span>
              {it.value > 0 && <span className="text-[17px] font-bold tracking-tight">{compactINR(it.value)}</span>}
              <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
            </Sheet>
          </Link>
        ))}
        {waiting === 0 && items.length === 0 && (
          <Sheet>{attention.isPending ? <Skeleton className="h-10 w-full" /> : <p className="py-2 text-center text-sm text-muted-foreground">{attention.isError ? 'Could not load this. Pull down or reopen the app to try again.' : 'Nothing needs you right now.'}</p>}</Sheet>
        )}
      </div>
    </div>
  )
}
