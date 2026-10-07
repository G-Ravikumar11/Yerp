import { useMemo, useState } from 'react'
import { Search, SlidersHorizontal, X } from 'lucide-react'
import { Button, Input, Select } from '@/components/ui'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'

export interface FilterOptions<T> {
  /** Everything in a row a person might search for. */
  search: (row: T) => string
  status?: (row: T) => string
  /** An ISO date (or a datetime); the range filters on its first ten characters. */
  date?: (row: T) => string
  /** Further things to narrow by - the project, the gang, the trade - each a drop-down of what the list holds. */
  facets?: Record<string, { label: string; get: (row: T) => string }>
}

export interface Facet {
  key: string
  label: string
  value: string
  options: string[]
  set: (v: string) => void
}

export interface ListFilters<T> {
  filtered: T[]
  total: number
  q: string
  status: string
  from: string
  to: string
  statuses: string[]
  facets: Facet[]
  hasStatus: boolean
  hasDate: boolean
  active: boolean
  setQ: (v: string) => void
  setStatus: (v: string) => void
  setFrom: (v: string) => void
  setTo: (v: string) => void
  clear: () => void
}

/**
 * Search, status and date filters over a list already in memory. Every list in
 * the app narrows the same way, so a person learns it once.
 */
export function useListFilters<T>(rows: readonly T[] | undefined, opts: FilterOptions<T>): ListFilters<T> {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [chosen, setChosen] = useState<Record<string, string>>({})
  const list = rows ?? []
  const facetDefs = opts.facets ?? {}

  const statuses = useMemo(() => (opts.status ? [...new Set(list.map(opts.status).filter(Boolean))].sort() : []), [list, opts.status])

  const facetOptions = useMemo(
    () => Object.fromEntries(Object.entries(facetDefs).map(([k, d]) => [k, [...new Set(list.map(d.get).filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [list],
  )

  const filtered = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean)
    return list.filter((row) => {
      if (words.length) {
        const text = opts.search(row).toLowerCase()
        // Amounts match with or without their commas.
        const hay = text + ' ' + text.replace(/,/g, '')
        if (!words.every((w) => hay.includes(w))) return false
      }
      if (status && opts.status && opts.status(row) !== status) return false
      for (const [k, d] of Object.entries(facetDefs)) if (chosen[k] && d.get(row) !== chosen[k]) return false
      if ((from || to) && opts.date) {
        const d = (opts.date(row) || '').slice(0, 10)
        if (!d || (from && d < from) || (to && d > to)) return false
      }
      return true
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list, q, status, from, to, chosen])

  return {
    filtered,
    total: list.length,
    q,
    status,
    from,
    to,
    statuses,
    facets: Object.entries(facetDefs)
      .map(([key, d]) => ({ key, label: d.label, value: chosen[key] ?? '', options: facetOptions[key] ?? [], set: (v: string) => setChosen((c) => ({ ...c, [key]: v })) }))
      .filter((f) => f.options.length > 1 || f.value),
    hasStatus: statuses.length > 0,
    hasDate: !!opts.date,
    active: !!(q || status || from || to || Object.values(chosen).some(Boolean)),
    setQ,
    setStatus,
    setFrom,
    setTo,
    clear: () => {
      setQ('')
      setStatus('')
      setFrom('')
      setTo('')
      setChosen({})
    },
  }
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** The few date ranges people actually ask for, as from/to dates. The financial year runs April to March. */
function presets(now = new Date()) {
  const first = new Date(now.getFullYear(), now.getMonth(), 1)
  const month30 = new Date(now)
  month30.setDate(month30.getDate() - 30)
  const fy = new Date(now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1, 3, 1)
  return [
    { label: 'This month', from: iso(first), to: iso(now) },
    { label: 'Last 30 days', from: iso(month30), to: iso(now) },
    { label: 'This financial year', from: iso(fy), to: iso(now) },
  ]
}

function Labelled({ label, active, className, children }: { label: string; active?: boolean; className?: string; children: React.ReactNode }) {
  return (
    <div className={cn('grid gap-1', className)}>
      <span className={cn('text-[11px] font-semibold uppercase tracking-wide', active ? 'text-primary' : 'text-muted-foreground')}>{label}</span>
      {children}
    </div>
  )
}

const activeSelect = 'border-primary bg-primary-soft font-medium'

/**
 * The filters over a list, laid out the same everywhere: a search box, then each filter with its name above it (the
 * ones in use lit), the dates with quick ranges, and under them what is being filtered on, each to be taken off by
 * itself. On a phone the filters fold away behind one button that says how many are on.
 */
export function FilterBar<T>({ filters, placeholder = 'Search...', children }: { filters: ListFilters<T>; placeholder?: string; children?: React.ReactNode }) {
  const f = filters
  const [open, setOpen] = useState(false)
  const chips: { key: string; text: string; off: () => void }[] = []
  if (f.q) chips.push({ key: 'q', text: `Search: “${f.q}”`, off: () => f.setQ('') })
  if (f.status) chips.push({ key: 'status', text: `Status: ${f.status.charAt(0) + f.status.slice(1).toLowerCase()}`, off: () => f.setStatus('') })
  for (const x of f.facets) if (x.value) chips.push({ key: x.key, text: `${x.label}: ${x.value}`, off: () => x.set('') })
  if (f.from || f.to) chips.push({ key: 'date', text: `Dated: ${f.from ? formatDate(f.from) : 'start'} to ${f.to ? formatDate(f.to) : 'today'}`, off: () => { f.setFrom(''); f.setTo('') } })
  const inUse = chips.filter((c) => c.key !== 'q').length
  const hasMore = f.hasStatus || f.facets.length > 0 || f.hasDate
  return (
    <div className="mb-4 grid gap-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="min-w-[14rem] flex-1 sm:max-w-md">
          <Input type="search" aria-label="Search" placeholder={placeholder} value={f.q} onChange={(e) => f.setQ(e.target.value)} leading={<Search />} className={cn(f.q && 'border-primary')} />
        </div>
        {hasMore && (
          <Button variant="outline" className="sm:hidden" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <SlidersHorizontal /> Filters{inUse ? ` (${inUse})` : ''}
          </Button>
        )}
        <span className="tabular ml-auto text-xs text-muted-foreground">{f.active ? `${f.filtered.length} of ${f.total} shown` : `${f.total} in the list`}</span>
        {children}
      </div>

      {hasMore && (
        <div className={cn('flex-wrap items-end gap-x-4 gap-y-3', open ? 'flex' : 'hidden', 'sm:flex')}>
          {f.hasStatus && (
            <Labelled label="Status" active={!!f.status} className="w-40">
              <Select aria-label="Status" className={cn(f.status && activeSelect)} value={f.status} onChange={(e) => f.setStatus(e.target.value)} placeholder="All" options={f.statuses.map((s) => ({ value: s, label: s.charAt(0) + s.slice(1).toLowerCase() }))} />
            </Labelled>
          )}
          {f.facets.map((x) => (
            <Labelled key={x.key} label={x.label} active={!!x.value} className="w-44">
              <Select aria-label={x.label} className={cn(x.value && activeSelect)} value={x.value} onChange={(e) => x.set(e.target.value)} placeholder="All" options={x.options.map((o) => ({ value: o, label: o }))} />
            </Labelled>
          ))}
          {f.hasDate && (
            <Labelled label="Dated" active={!!(f.from || f.to)}>
              <div className="flex flex-wrap items-center gap-1.5">
                <Input type="date" aria-label="From date" className={cn('w-[9.5rem]', f.from && 'border-primary')} value={f.from} onChange={(e) => f.setFrom(e.target.value)} />
                <span className="text-xs text-muted-foreground">to</span>
                <Input type="date" aria-label="To date" className={cn('w-[9.5rem]', f.to && 'border-primary')} value={f.to} onChange={(e) => f.setTo(e.target.value)} />
                {presets().map((p) => (
                  <Button key={p.label} type="button" size="sm" variant={f.from === p.from && f.to === p.to ? 'secondary' : 'ghost'} onClick={() => { f.setFrom(p.from); f.setTo(p.to) }}>
                    {p.label}
                  </Button>
                ))}
              </div>
            </Labelled>
          )}
        </div>
      )}

      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Filters in use">
          {chips.map((c) => (
            <button key={c.key} type="button" onClick={c.off} aria-label={`Remove filter ${c.text}`} className="inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary-soft px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-primary/20">
              {c.text} <X className="size-3" />
            </button>
          ))}
          <Button variant="ghost" size="sm" onClick={f.clear}>
            Clear all
          </Button>
        </div>
      )}
    </div>
  )
}
