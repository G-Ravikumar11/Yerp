import type { CostMix } from '@/api/costs'
import { formatINR } from '@/lib/utils'

const COLOURS: Record<string, string> = { labour: '#4f46e5', materials: '#0ea5e9', subcontract: '#f59e0b', plant: '#8b5cf6', other: '#94a3b8' }

/** Where the money went, by heading: a single total says a job is losing money, the split says whether it was bought badly or built slowly. */
export function CostMixBar({ categories }: { categories: CostMix[] }) {
  const live = categories.filter((c) => c.amount > 0)
  const total = live.reduce((t, c) => t + c.amount, 0)
  if (!total) return null
  return (
    <div>
      <div className="mb-3 flex h-3 overflow-hidden rounded-md" role="img" aria-label="Cost by heading">{live.map((c) => <div key={c.key} title={c.label} style={{ width: `${(c.amount / total) * 100}%`, background: COLOURS[c.key] ?? '#94a3b8' }} />)}</div>
      <ul className="flex flex-wrap gap-x-5 gap-y-1.5 text-[13px]">{live.map((c) => <li key={c.key} className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: COLOURS[c.key] ?? '#94a3b8' }} />{c.label} <strong>{formatINR(c.amount)}</strong> <span className="text-muted-foreground">{Math.round((c.amount / total) * 100)}%</span></li>)}</ul>
    </div>
  )
}
