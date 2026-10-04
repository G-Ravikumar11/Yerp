import { useMemo, useState } from 'react'
import { Search, X } from 'lucide-react'
import { Button, Input, Select } from '@/components/ui'

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

export function FilterBar<T>({ filters, placeholder = 'Search...', children }: { filters: ListFilters<T>; placeholder?: string; children?: React.ReactNode }) {
  const f = filters
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2.5">
      <div className="min-w-[14rem] flex-1 sm:max-w-sm">
        <Input type="search" aria-label="Search" placeholder={placeholder} value={f.q} onChange={(e) => f.setQ(e.target.value)} leading={<Search />} />
      </div>
      {f.hasStatus && (
        <div className="w-44">
          <Select aria-label="Status" value={f.status} onChange={(e) => f.setStatus(e.target.value)} placeholder="All statuses" options={f.statuses.map((s) => ({ value: s, label: s.charAt(0) + s.slice(1).toLowerCase() }))} />
        </div>
      )}
      {f.facets.map((x) => (
        <div key={x.key} className="w-44">
          <Select aria-label={x.label} value={x.value} onChange={(e) => x.set(e.target.value)} placeholder={`All ${x.label.toLowerCase()}`} options={x.options.map((o) => ({ value: o, label: o }))} />
        </div>
      ))}
      {f.hasDate && (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Input type="date" aria-label="From date" className="w-[9.5rem]" value={f.from} onChange={(e) => f.setFrom(e.target.value)} />
          to
          <Input type="date" aria-label="To date" className="w-[9.5rem]" value={f.to} onChange={(e) => f.setTo(e.target.value)} />
        </div>
      )}
      {f.active && (
        <Button variant="ghost" size="sm" onClick={f.clear}>
          <X /> Clear
        </Button>
      )}
      <span className="tabular ml-auto text-xs text-muted-foreground">{f.active ? `${f.filtered.length} of ${f.total}` : `${f.total} in the list`}</span>
      {children}
    </div>
  )
}
