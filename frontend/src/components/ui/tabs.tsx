import { motion } from 'framer-motion'
import { useId } from 'react'
import { cn } from '@/lib/utils'

export interface TabItem<V extends string> {
  value: V
  label: string
  /** A count, shown quietly beside the label. */
  count?: number
}

/** A row of tabs with a marker that slides to the chosen one. */
export function Tabs<V extends string>({ items, value, onChange, label }: { items: readonly TabItem<V>[]; value: V; onChange: (v: V) => void; label: string }) {
  const id = useId()
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto rounded-xl bg-muted p-1">
      {items.map((t) => {
        const on = t.value === value
        return (
          <button
            key={t.value}
            role="tab"
            type="button"
            aria-selected={on}
            onClick={() => onChange(t.value)}
            className={cn(
              'relative shrink-0 whitespace-nowrap rounded-lg px-3.5 py-1.5 text-[13px] font-medium transition-colors',
              on ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {on && <motion.span layoutId={`tab-${id}`} className="absolute inset-0 rounded-lg bg-card shadow-xs" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />}
            <span className="relative">
              {t.label}
              {t.count !== undefined && <span className="tabular ml-1.5 text-xs text-subtle">{t.count}</span>}
            </span>
          </button>
        )
      })}
    </div>
  )
}
