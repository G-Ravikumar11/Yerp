import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { Input } from '@/components/ui'
import { scanCode, scanWhat, useItemSearch, type StoreItemOption } from '@/api/store'
import { ApiError } from '@/lib/api'
import { toast } from '@/stores/toast'
import { ScanButton } from './Scanner'

export interface ItemPickerProps {
  /** The chosen item, or null. Hold the whole option so the box can show its name without looking it up again. */
  value: StoreItemOption | null
  onChange: (item: StoreItemOption | null) => void
  placeholder?: string
  disabled?: boolean
  id?: string
  'aria-invalid'?: boolean
}

/** Type to find a stock item by code or name and pick it from the list - or scan its rack label or the maker's barcode with the
    camera. A handheld scanner types the code and presses Enter, which takes the item that has it. */
export function ItemPicker({ value, onChange, placeholder = 'Search item code or name', disabled, id, ...rest }: ItemPickerProps) {
  const [text, setText] = useState('')
  const [typed, setTyped] = useState('')
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
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
  // A scanned code, or one typed and Entered: the item it belongs to, if any.
  const take = async (code: string, quiet = false) => {
    try {
      const found = await scanCode(code)
      if (found.kind === 'item') {
        onChange(found.item)
        setOpen(false)
        setText('')
      } else toast.error(`That is ${scanWhat(found)}, not an item.`)
    } catch (e) {
      if (!quiet) toast.error(e instanceof ApiError ? e.message : 'The code could not be looked up.')
    }
  }

  if (value) {
    return (
      <div className="flex h-10 items-center justify-between gap-2 rounded-md border border-input px-3 text-sm">
        <span className="min-w-0 truncate">
          <span className="font-mono text-xs text-muted-foreground">{value.code}</span> {value.name}
        </span>
        {!disabled && (
          <button
            type="button"
            aria-label="Clear item"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => {
              onChange(null)
              setText('')
            }}
          >
            <X className="size-4" />
          </button>
        )}
      </div>
    )
  }
  return (
    <div ref={box} className="relative flex gap-2">
      <div className="min-w-0 flex-1">
      <Input
        id={id}
        aria-invalid={rest['aria-invalid']}
        leading={<Search />}
        value={text}
        disabled={disabled}
        placeholder={placeholder}
        autoComplete="off"
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setText(e.target.value)
          setOpen(true)
        }}
        onKeyDown={(e) => {
          if (e.key !== 'Enter' || !text.trim()) return
          e.preventDefault()
          void take(text.trim(), true)
        }}
      />
      </div>
      {!disabled && <ScanButton title="Scan the item" hint="The QR on its rack label, or the maker's barcode on the bag, can or box." onCode={(c) => void take(c)} />}
      {open && (
        <ul role="listbox" className="absolute top-full z-30 mt-1 max-h-64 w-full overflow-auto rounded-md border border-input bg-popover py-1 text-sm shadow-md">
          {(q.data ?? []).map((it) => (
            <li key={it.id} role="option" aria-selected={false}>
              <button
                type="button"
                className="flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left hover:bg-accent"
                onClick={() => {
                  onChange(it)
                  setOpen(false)
                  setText('')
                }}
              >
                <span className="min-w-0 truncate">
                  <span className="font-mono text-xs text-muted-foreground">{it.code}</span> {it.name}
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">{it.base_uom}</span>
              </button>
            </li>
          ))}
          {!q.isFetching && !(q.data ?? []).length && <li className="px-3 py-2 text-muted-foreground">No item found</li>}
        </ul>
      )}
    </div>
  )
}
