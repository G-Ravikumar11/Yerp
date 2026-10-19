import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search } from 'lucide-react'
import { JOB_STATUS, useBoard, useProjects, type Project } from '@/api/projects'
import { Skeleton } from '@/components/ui'
import { useSession } from '@/lib/session'
import { cn, compactINR } from '@/lib/utils'
import { LargeTitle, Pill } from './ui'

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'quoting', label: 'Quoting' },
  { value: 'complete', label: 'Done' },
] as const

const tone = (s: string) => (s === 'in_progress' ? 'info' : s === 'won' || s === 'complete' ? 'ok' : s === 'on_hold' ? 'warn' : s === 'cancelled' ? 'bad' : 'quiet') as 'info' | 'ok' | 'warn' | 'bad' | 'quiet'

/** Every project as a card with its status and, for those who see money, how much of its budget is spent. */
export default function ProjectsCards() {
  const { can } = useSession()
  const projects = useProjects()
  const board = useBoard()
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['value']>('all')
  const money = useMemo(() => new Map((can('reports.view') ? (board.data?.jobs ?? []) : []).map((j) => [j.id, j.costing])), [board.data, can])
  const all = projects.data ?? []
  const shown = all
    .filter((p) => filter === 'all' || p.status === filter)
    .filter((p) => !q.trim() || `${p.number} ${p.name} ${p.customer_name}`.toLowerCase().includes(q.trim().toLowerCase()))
  const count = (v: string) => (v === 'all' ? all.length : all.filter((p) => p.status === v).length)

  return (
    <div className="pb-4">
      <LargeTitle title="Projects" sub={projects.data ? `${all.length} in all` : undefined} />
      <label className="flex h-11 items-center gap-2.5 rounded-lg bg-card px-3.5 text-muted-foreground focus-within:ring-2 focus-within:ring-primary/50">
        <Search className="size-[18px]" aria-hidden />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${all.length || ''} projects`.replace('  ', ' ')} aria-label="Search projects" className="h-full min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none placeholder:text-muted-foreground" />
      </label>
      <div role="tablist" aria-label="Status" className="-mx-4 mt-3 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {FILTERS.map((f) => (
          <button key={f.value} role="tab" aria-selected={filter === f.value} type="button" onClick={() => setFilter(f.value)} className={cn('h-9 shrink-0 rounded-md px-4 text-sm font-medium', filter === f.value ? 'bg-primary text-primary-foreground' : 'bg-card')}>
            {f.label} <span className="opacity-70">{count(f.value)}</span>
          </button>
        ))}
      </div>

      {/* One card wide on a phone, two on a tablet or an unfolded one, three on a large one. */}
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {projects.isPending && [0, 1, 2].map((i) => <Skeleton key={i} className="h-32 w-full rounded-lg" />)}
        {projects.isError && <p className="col-span-full rounded-lg bg-card p-4 text-center text-sm text-muted-foreground">Could not load the projects. Check the connection and try again.</p>}
        {projects.isSuccess && shown.length === 0 && <p className="col-span-full rounded-lg bg-card p-6 text-center text-sm text-muted-foreground">{all.length ? 'No project matches.' : 'No projects yet.'}</p>}
        {shown.map((p) => <Card key={p.id} p={p} costing={money.get(p.id)} />)}
      </div>
    </div>
  )
}

function Card({ p, costing }: { p: Project; costing?: { budget?: number; used?: number; remaining?: number } }) {
  const used = costing?.used ?? 0
  const budget = costing?.budget ?? p.budget ?? 0
  const pct = budget > 0 ? Math.min(100, Math.round((used / budget) * 100)) : 0
  return (
    <Link to={`/projects/${p.id}`} className="block rounded-lg border border-border bg-card p-4 active:scale-[0.99]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold tracking-wide text-muted-foreground">{p.number}</div>
          <h3 className="mt-0.5 text-[17px] font-semibold leading-snug">{p.name}</h3>
          {p.customer_name && <div className="mt-0.5 truncate text-[13px] text-muted-foreground">{p.customer_name}</div>}
        </div>
        <Pill tone={tone(p.status)}>{JOB_STATUS[p.status] ?? p.status}</Pill>
      </div>
      {budget > 0 && (
        <>
          <div className="mt-3.5 h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Budget used" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className={cn('h-full rounded-full', pct > 90 ? 'bg-danger' : pct > 75 ? 'bg-warning' : 'bg-primary')} style={{ width: `${pct}%` }} />
          </div>
          <div className="mt-2 flex justify-between text-[13px] text-muted-foreground">
            <span><b className="font-semibold text-foreground">{pct}%</b> of budget used</span>
            <span>Left <b className="font-semibold text-foreground">{compactINR(Math.max(0, budget - used))}</b></span>
          </div>
        </>
      )}
    </Link>
  )
}
