import { motion } from 'framer-motion'
import { useId } from 'react'
import { cn } from '@/lib/utils'

export interface TabItem<V extends string> {
  value: V
  label: string
  /** A count, shown quietly beside the label. */
  count?: number
}

/**
 * A row of tabs with a marker that slides to the chosen one. size="lg" is for the top level of a page with only a
 * few sections: a size up from the usual tabs.
 */
export function Tabs<V extends string>({ items, value, onChange, label, size = 'md' }: { items: readonly TabItem<V>[]; value: V; onChange: (v: V) => void; label: string; size?: 'md' | 'lg' }) {
  const id = useId()
  const lg = size === 'lg'
  return (
    <div role="tablist" aria-label={label} className={cn('flex gap-1 overflow-x-auto bg-muted', lg ? 'w-fit rounded-xl p-1' : 'rounded-xl p-1')}>
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
              'relative shrink-0 whitespace-nowrap transition-colors',
              lg ? 'rounded-lg px-5 py-2 text-[14.5px] font-semibold' : 'rounded-lg px-3.5 py-1.5 text-[13px] font-medium',
              on ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {on && <motion.span layoutId={`tab-${id}`} className={cn('absolute inset-0 bg-card shadow-xs', 'rounded-lg')} transition={{ type: 'spring', stiffness: 500, damping: 38 }} />}
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
