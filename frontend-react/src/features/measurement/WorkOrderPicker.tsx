import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Check, ChevronsUpDown, Search } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Order } from '@/api/orders'

export type JobCodeOf = (o: Order) => string

/** Everything a person might type to find an order: its number, job code, project, gang or subject. */
const haystack = (o: Order, jobCode: JobCodeOf) => [o.wo_number, jobCode(o), o.project, o.contractor, o.vendor_code, o.subject, o.work_type].join(' ').toLowerCase()

/**
 * Pick from every work order by typing any part of its number, job code,
 * project or gang. Keyboard all the way: arrows move, Enter chooses, Esc closes.
 */
export function WorkOrderPicker({ orders, value, onChange, jobCode, loading }: { orders: Order[]; value: number; onChange: (id: number) => void; jobCode: JobCodeOf; loading?: boolean }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const listId = useId()
  const current = orders.find((o) => o.id === value)

  const shown = useMemo(() => {
    const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean)
    const hits = words.length ? orders.filter((o) => words.every((w) => haystack(o, jobCode).includes(w))) : orders
    // Numbers that start with what was typed come first.
    const first = q.trim().toLowerCase()
    return [...hits].sort((a, b) => Number(b.wo_number.toLowerCase().startsWith(first)) - Number(a.wo_number.toLowerCase().startsWith(first)))
  }, [orders, q, jobCode])

  useEffect(() => {
    if (!open) return
    input.current?.focus()
    const away = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', away)
    return () => document.removeEventListener('pointerdown', away)
  }, [open])

  useEffect(() => {
    document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: 'nearest' })
  }, [active, listId])

  const close = () => {
    setOpen(false)
    setQ('')
    trigger.current?.focus()
  }
  const choose = (o: Order | undefined) => {
    if (!o) return
    onChange(o.id)
    close()
  }

  return (
    <div ref={root} className="relative min-w-0">
      <button
        ref={trigger}
        type="button"
        aria-label="Work order"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => {
          setActive(Math.max(0, orders.findIndex((o) => o.id === value)))
          setOpen((o) => !o)
        }}
        className="flex h-11 w-full items-center gap-3 rounded-md border border-input bg-card px-3 text-left text-sm transition-[border-color,box-shadow] hover:border-subtle/60 focus-visible:border-ring focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/15"
      >
        {current ? (
          <span className="flex min-w-0 flex-1 items-baseline gap-2">
            <span className="shrink-0 whitespace-nowrap font-mono text-[13px] font-semibold">{current.wo_number}</span>
            {jobCode(current) && <span className="shrink-0 rounded bg-primary-soft px-1.5 py-0.5 font-mono text-[11px] text-primary">{jobCode(current)}</span>}
            <span className="truncate text-muted-foreground">{current.contractor || 'no gang'}</span>
            {current.status === 'AMENDED' && <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">amended</span>}
          </span>
        ) : (
          <span className="flex-1 text-subtle">{loading ? 'Loading...' : 'No approved work orders yet'}</span>
        )}
        <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1.5 overflow-hidden rounded-lg border border-border bg-popover shadow-lg sm:min-w-[32rem]">
          <div className="flex items-center gap-2 border-b border-border px-3">
            <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <input
              ref={input}
              role="combobox"
              aria-expanded
              aria-controls={listId}
              aria-activedescendant={shown[active] ? `${listId}-${active}` : undefined}
              aria-label="Find a work order by number, job code, project or gang"
              value={q}
              placeholder="Work order no., job code, project or gang"
              onChange={(e) => {
                setQ(e.target.value)
                setActive(0)
              }}
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  setActive((a) => Math.min(shown.length - 1, a + 1))
                } else if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  setActive((a) => Math.max(0, a - 1))
                } else if (e.key === 'Enter') {
                  e.preventDefault()
                  choose(shown[active])
                } else if (e.key === 'Escape') {
                  e.preventDefault()
                  e.stopPropagation()
                  close()
                }
              }}
              className="h-11 w-full bg-transparent text-sm outline-none placeholder:text-subtle"
            />
          </div>
          <ul id={listId} role="listbox" aria-label="Work orders" className="max-h-80 overflow-y-auto py-1">
            {shown.length === 0 && <li className="px-3 py-6 text-center text-[13px] text-muted-foreground">No work order matches that.</li>}
            {shown.map((o, i) => (
              <li
                key={o.id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={o.id === value}
                onPointerEnter={() => setActive(i)}
                onClick={() => choose(o)}
                className={cn('flex cursor-pointer items-center gap-3 px-3 py-2', i === active && 'bg-accent')}
              >
                <Check className={cn('size-4 shrink-0 text-primary', o.id !== value && 'invisible')} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2">
                    <span className="shrink-0 whitespace-nowrap font-mono text-[13px] font-semibold">{o.wo_number}</span>
                    {jobCode(o) && <span className="shrink-0 rounded bg-primary-soft px-1.5 py-0.5 font-mono text-[11px] text-primary">{jobCode(o)}</span>}
                    {o.status === 'AMENDED' && <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">amended</span>}
                    <span className="truncate text-[13px]">{o.contractor || 'no gang'}</span>
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {o.project}
                    {o.subject ? ` · ${o.subject}` : ''}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <p className="border-t border-border px-3 py-1.5 text-[11px] text-muted-foreground">
            {shown.length} of {orders.length} work orders · Up and down to move, Enter to open, Esc to close
          </p>
        </div>
      )}
    </div>
  )
}
