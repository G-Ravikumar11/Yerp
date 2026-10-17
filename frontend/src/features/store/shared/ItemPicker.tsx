import { useEffect, useId, useRef, useState } from 'react'
import { Loader2, Search, X } from 'lucide-react'
import { Input } from '@/components/ui'
import { useItemSearch, type StoreItemOption } from '@/api/store'

export interface ItemPickerProps {
  /** The chosen item, or null. Hold the whole option so the box can show its name without looking it up again. */
  value: StoreItemOption | null
  onChange: (item: StoreItemOption | null) => void
  placeholder?: string
  disabled?: boolean
  id?: string
  'aria-invalid'?: boolean
}

/** Where the highlight goes for a key press in a list of `count` options (-1 = none highlighted). */
export function nextIndex(current: number, key: string, count: number): number {
  if (!count) return -1
  if (key === 'ArrowDown') return current < count - 1 ? current + 1 : 0
  if (key === 'ArrowUp') return current > 0 ? current - 1 : count - 1
  if (key === 'Home') return 0
  if (key === 'End') return count - 1
  return current
}

/** "kg · also bag, MT": the units an item can be entered in. */
export function unitsLine(item: Pick<StoreItemOption, 'base_uom' | 'uoms'>): string {
  const others = (item.uoms ?? []).map((u) => u.code).filter((c) => c && c.toLowerCase() !== item.base_uom.toLowerCase())
  return others.length ? `${item.base_uom} · also ${others.join(', ')}` : item.base_uom
}

/** Type to find a stock item by code or name; pick one with the mouse or the arrow keys and Enter. */
export function ItemPicker({ value, onChange, placeholder = 'Search item code or name', disabled, id, ...rest }: ItemPickerProps) {
  const [text, setText] = useState('')
  const [typed, setTyped] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const box = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const listId = useId()
  useEffect(() => {
    const t = setTimeout(() => setTyped(text.trim()), 200)
    return () => clearTimeout(t)
  }, [text])
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])
  const q = useItemSearch(typed)
  const options = q.data ?? []
  // Whether the list on show is the answer to what is in the box. While the search is still on its way the old list
  // stays up (so it does not flicker), but nothing in it is highlighted and Enter does not take it.
  const fresh = typed === text.trim() && !q.isPlaceholderData
  // The highlight stays inside the list as it changes; typing puts it back on the first (best) match, so Enter takes it.
  const hi = fresh && options.length ? Math.min(Math.max(active, 0), options.length - 1) : -1
  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-index="${hi}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [hi])

  const choose = (it: StoreItemOption) => {
    onChange(it)
    setOpen(false)
    setText('')
  }

  if (value) {
    return (
      <div className="flex h-10 items-center justify-between gap-2 rounded-md border border-input px-3 text-sm" title={unitsLine(value)}>
        <span className="min-w-0 truncate">
          <span className="font-mono text-xs text-muted-foreground">{value.code}</span> {value.name}
        </span>
        {!disabled && (
          <button
            type="button"
            aria-label="Clear item"
            className="rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => {
              onChange(null)
              setText('')
              setTimeout(() => input.current?.focus(), 0)
            }}
          >
            <X className="size-4" />
          </button>
        )}
      </div>
    )
  }
  return (
    <div ref={box} className="relative">
      <Input
        ref={input}
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && hi >= 0 ? `${listId}-${hi}` : undefined}
        aria-invalid={rest['aria-invalid']}
        leading={<Search />}
        trailing={q.isFetching ? <Loader2 className="animate-spin" /> : undefined}
        value={text}
        disabled={disabled}
        placeholder={placeholder}
        autoComplete="off"
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setText(e.target.value)
          setOpen(true)
          setActive(0)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || ((e.key === 'Home' || e.key === 'End') && open)) {
            e.preventDefault()
            setOpen(true)
            setActive(nextIndex(hi, e.key, options.length))
          } else if (e.key === 'Enter' && open) {
            e.preventDefault() // never submits the form around it; waits for the answer to what was typed
            if (hi >= 0) choose(options[hi])
          } else if (e.key === 'Escape' && open) {
            e.preventDefault()
            e.stopPropagation() // close the list, not the dialog it sits in
            setOpen(false)
          } else if (e.key === 'Tab') {
            setOpen(false)
          }
        }}
      />
      {open && (
        <ul ref={list} id={listId} role="listbox" className="absolute z-30 mt-1 max-h-64 w-full overflow-auto rounded-md border border-input bg-popover py-1 text-sm shadow-lg">
          {options.map((it, i) => (
            <li
              key={it.id}
              id={`${listId}-${i}`}
              data-index={i}
              role="option"
              aria-selected={i === hi}
              className={i === hi ? 'bg-accent' : undefined}
              onMouseEnter={() => setActive(i)}
              // mousedown, not click: the input keeps its focus and the list does not close first
              onMouseDown={(e) => {
                e.preventDefault()
                choose(it)
              }}
            >
              <div className="flex w-full cursor-pointer items-baseline justify-between gap-3 px-3 py-2 text-left">
                <span className="min-w-0 truncate">
                  <span className="font-mono text-xs text-muted-foreground">{it.code}</span> {it.name}
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">{unitsLine(it)}</span>
              </div>
            </li>
          ))}
          {!q.isFetching && !options.length && (
            <li className="px-3 py-2 text-muted-foreground">{typed ? `No item matches "${typed}"` : 'No stock items'}</li>
          )}
          {q.isFetching && !options.length && <li className="px-3 py-2 text-muted-foreground">Searching...</li>}
        </ul>
      )}
    </div>
  )
}
