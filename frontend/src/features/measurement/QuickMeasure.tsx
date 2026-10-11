import { forwardRef, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { Keyboard } from 'lucide-react'
import type { MbLine } from '@/api/mb'
import { cn } from '@/lib/utils'
import { Input } from '@/components/ui'
import { ItemFacts } from './ItemFacts'

export interface QuickMeasureHandle {
  focus: () => void
}

const codes = (l: MbLine) => [l.activity_no, l.item_code].filter(Boolean).map((c) => (c as string).toLowerCase())

/**
 * Type an item code (the activity number or the item code) and everything else
 * about that item - the description, unit, rate, what is ordered and what is
 * left - fills in from the work order being measured. Enter starts the measurement.
 */
export const QuickMeasure = forwardRef<QuickMeasureHandle, { lines: MbLine[]; onPick: (l: MbLine) => void }>(({ lines, onPick }, ref) => {
  const [code, setCode] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  useImperativeHandle(ref, () => ({
    focus: () => {
      setCode('')
      input.current?.focus()
    },
  }))

  const matches = useMemo(() => {
    const q = code.trim().toLowerCase()
    if (!q) return []
    const items = lines.filter((l) => !l.is_header)
    const rank = (l: MbLine) => (codes(l).includes(q) ? 0 : codes(l).some((c) => c.startsWith(q)) ? 1 : 2)
    return items
      .filter((l) => codes(l).some((c) => c.includes(q)) || l.description.toLowerCase().includes(q))
      .sort((a, b) => rank(a) - rank(b))
      .slice(0, 6)
  }, [code, lines])

  const hit = matches[Math.min(active, matches.length - 1)]
  const typed = code.trim() !== ''

  return (
    <div>
      <Input
        ref={input}
        aria-label="Item code"
        value={code}
        placeholder="Type an item code to measure it (e.g. 1.2)"
        leading={<Keyboard />}
        autoComplete="off"
        onChange={(e) => {
          setCode(e.target.value)
          setActive(0)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' && matches.length) {
            e.preventDefault()
            setActive((a) => Math.min(matches.length - 1, a + 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setActive((a) => Math.max(0, a - 1))
          } else if (e.key === 'Enter' && hit) {
            e.preventDefault()
            onPick(hit)
          } else if (e.key === 'Escape') {
            setCode('')
          }
        }}
      />
      {typed && !hit && <p className="mt-2 text-[13px] text-muted-foreground">No item with that code on this work order.</p>}
      {hit && (
        <div aria-live="polite" className="mt-2 rounded-lg border border-border bg-card p-3">
          <div className="mb-2 flex items-baseline gap-2">
            <span className="font-mono text-xs font-semibold text-primary">{hit.activity_no}</span>
            {hit.item_code && <span className="font-mono text-xs text-muted-foreground">{hit.item_code}</span>}
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{hit.description}</span>
            <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">Enter to measure</span>
          </div>
          <ItemFacts line={hit} />
          {matches.length > 1 && (
            <ul aria-label="Other matches" className="mt-2 flex flex-wrap gap-1.5 border-t border-border pt-2">
              {matches.map((m, i) => (
                <li key={m.item_id}>
                  <button
                    type="button"
                    onClick={() => onPick(m)}
                    onPointerEnter={() => setActive(i)}
                    className={cn('rounded-full border px-2.5 py-0.5 text-xs transition-colors', m === hit ? 'border-primary/40 bg-primary-soft text-primary' : 'border-border text-muted-foreground hover:text-foreground')}
                  >
                    <span className="font-mono">{m.activity_no}</span> {m.description.slice(0, 28)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
})
QuickMeasure.displayName = 'QuickMeasure'
