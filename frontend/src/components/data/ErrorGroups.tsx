import type { ErrorGroup } from '@/api/errorLog'

/** The errors by cause: each code on each screen, how often, and when last - most first. */
export function ErrorGroups({ groups, onPick }: { groups: ErrorGroup[]; onPick?: (g: ErrorGroup) => void }) {
  if (!groups.length) return null
  const shown = groups.slice(0, 8)
  return (
    <section aria-label="Errors by cause" className="mb-4 rounded-xl border border-border bg-card p-3">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">By cause - {groups.length} in all</p>
      <ul className="grid gap-1 text-[13px]">
        {shown.map((g) => (
          <li key={`${g.code}${g.screen}${g.company ?? ''}`} className="flex flex-wrap items-baseline gap-x-2">
            <strong className="tabular w-10 text-right">{g.count}x</strong>
            <span className="font-mono text-xs">{g.code}</span>
            {onPick ? <button type="button" className="font-mono text-xs text-primary hover:underline" onClick={() => onPick(g)}>{g.screen}</button> : <span className="font-mono text-xs">{g.screen}</span>}
            {g.company && <span className="text-xs text-muted-foreground">{g.company}</span>}
            <span className="ml-auto text-xs text-muted-foreground">last {g.last_at} · ref {g.last_ref}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
