import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/utils'
import type { Column, Option } from './types'
import { optionLabel, optionValue } from './values'

export type Move = 'down' | 'up' | 'right' | 'left' | 'none'

export interface CellEditorProps<T> {
  column: Column<T>
  /** What the box starts with: the typed character, or the cell's current text. */
  initial: string
  /**
   * `enter`: begun by typing - the arrow keys leave the cell, as in Excel.
   * `edit`: begun by F2 or a double click - the arrow keys move the caret.
   */
  mode: 'enter' | 'edit'
  /** For a picker begun with F2: what it holds now, so it can be highlighted. */
  currentLabel?: string
  onTextChange: (text: string) => void
  /** Returns why it cannot be saved, or null when it was. */
  onCommit: (text: string, move: Move) => string | null
  onCancel: () => void
  /** Focus went somewhere else entirely: keep the value if it is good, else drop it. */
  onBlurAway: (text: string) => void
}

const arrows: Record<string, Move> = { ArrowDown: 'down', ArrowUp: 'up', ArrowRight: 'right', ArrowLeft: 'left' }

/** Picks that start with what was typed first, then those that merely contain it. */
export function filterOptions(options: readonly Option[], text: string): Option[] {
  const w = text.trim().toLowerCase()
  if (!w) return options.slice()
  const starts: Option[] = []
  const has: Option[] = []
  for (const o of options) {
    const l = optionLabel(o).toLowerCase()
    const v = optionValue(o).toLowerCase()
    if (l.startsWith(w) || v.startsWith(w)) starts.push(o)
    else if (l.includes(w) || v.includes(w)) has.push(o)
  }
  return [...starts, ...has]
}

/**
 * The box that sits in a cell while it is being changed. One component for
 * every column type: a picker adds a list under it, everything else is just
 * a text box - what was typed is turned into a value by the column, not here.
 */
export function CellEditor<T>({
  column,
  initial,
  mode,
  currentLabel,
  onTextChange,
  onCommit,
  onCancel,
  onBlurAway,
}: CellEditorProps<T>) {
  const [text, setText] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const [hi, setHi] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const done = useRef(false)
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null)
  const isSelect = column.type === 'select'
  const options = useMemo(() => (isSelect ? filterOptions(column.options ?? [], text) : []), [isSelect, column.options, text])

  useLayoutEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.focus({ preventScroll: true })
    el.setSelectionRange(el.value.length, el.value.length)
  }, [])

  // Where to float the list: measured here, once the box is on the page, and
  // again when the sheet scrolls or the window changes under it.
  useLayoutEffect(() => {
    if (!isSelect) return
    const measure = () => setAnchorRect(boxRef.current?.getBoundingClientRect() ?? null)
    measure()
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [isSelect])

  // A picker opened with F2 starts on the answer it already has.
  useLayoutEffect(() => {
    if (!isSelect) return
    if (!text && currentLabel) {
      const at = options.findIndex((o) => optionLabel(o) === currentLabel)
      setHi(at >= 0 ? at : 0)
    } else setHi(0)
    // Only when the list itself changes shape.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSelect, text])

  const finish = (value: string, move: Move) => {
    // Marked done first: committing hands focus back to the sheet, and that
    // blur must not commit the same value a second time.
    done.current = true
    const err = onCommit(value, move)
    if (err) {
      done.current = false
      setError(err)
    }
  }

  const choose = (move: Move) => {
    if (!isSelect) return finish(text, move)
    const pick = options[hi]
    if (pick) return finish(optionLabel(pick), move)
    if (!text.trim()) return finish(currentLabel ?? '', move)
    if (column.freeText) return finish(text.trim(), move)
    setError('Not one of the choices')
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing) return
    const stop = () => {
      e.preventDefault()
      e.stopPropagation()
    }
    if (e.key === 'Enter') {
      stop()
      choose(e.shiftKey ? 'up' : 'down')
    } else if (e.key === 'Tab') {
      stop()
      choose(e.shiftKey ? 'left' : 'right')
    } else if (e.key === 'Escape') {
      stop()
      done.current = true
      onCancel()
    } else if (isSelect && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      stop()
      if (options.length) setHi((h) => (h + (e.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length)
    } else if (arrows[e.key] && mode === 'enter' && !isSelect) {
      stop()
      finish(text, arrows[e.key])
    } else {
      e.stopPropagation()
    }
  }

  const numeric = column.type === 'number'

  return (
    <div
      ref={boxRef}
      data-cell-editor
      // The box and its list of choices sit inside the cell in the page's tree: a click on either must not
      // reach the cell and close the editor before the click lands.
      onMouseDown={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
      className="absolute inset-0 z-30"
    >
      <input
        ref={inputRef}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          setError(null)
          onTextChange(e.target.value)
        }}
        onKeyDown={onKeyDown}
        onBlur={() => {
          if (!done.current) onBlurAway(text)
        }}
        inputMode={numeric ? 'decimal' : undefined}
        spellCheck={false}
        autoComplete="off"
        aria-label={column.header}
        aria-invalid={error ? true : undefined}
        aria-autocomplete={isSelect ? 'list' : undefined}
        aria-expanded={isSelect ? true : undefined}
        placeholder={isSelect ? (currentLabel ?? column.placeholder) : column.type === 'date' ? 'dd-mm-yyyy' : undefined}
        className={cn(
          'size-full bg-card px-2.5 text-[13px] text-foreground outline-none',
          'shadow-[inset_0_0_0_2px_var(--primary)] placeholder:text-subtle',
          numeric && 'tabular text-right',
          column.mono && 'font-mono',
          error && 'shadow-[inset_0_0_0_2px_var(--danger)]',
        )}
      />
      {error && (
        <div
          role="alert"
          className="pointer-events-none absolute left-0 top-full z-40 mt-1 whitespace-nowrap rounded-md bg-danger px-2 py-1 text-xs font-medium text-white shadow-lift"
        >
          {error}
        </div>
      )}
      {isSelect && <OptionList rect={anchorRect} options={options} highlighted={hi} onPick={(o) => finish(optionLabel(o), 'down')} />}
    </div>
  )
}

/** The picker's list, floated over the sheet so a short grid does not clip it. */
function OptionList({
  rect,
  options,
  highlighted,
  onPick,
}: {
  rect: DOMRect | null
  options: Option[]
  highlighted: number
  onPick: (o: Option) => void
}) {
  const listRef = useRef<HTMLUListElement>(null)

  useLayoutEffect(() => {
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [highlighted, options])

  if (!rect) return null
  const below = window.innerHeight - rect.bottom
  const flip = below < 220 && rect.top > below
  return createPortal(
    <ul
      ref={listRef}
      role="listbox"
      style={{
        left: rect.left,
        width: Math.max(rect.width, 200),
        ...(flip ? { bottom: window.innerHeight - rect.top } : { top: rect.bottom }),
      }}
      className="fixed z-[70] max-h-60 overflow-y-auto rounded-lg border border-border bg-popover p-1 text-[13px] shadow-pop"
    >
      {options.length === 0 && <li className="px-2.5 py-2 text-muted-foreground">No match</li>}
      {options.map((o, i) => (
        <li
          key={optionValue(o)}
          role="option"
          aria-selected={i === highlighted}
          // Keep focus in the box: clicking a choice must not count as leaving it.
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => onPick(o)}
          className={cn('cursor-pointer rounded-md px-2.5 py-1.5', i === highlighted ? 'bg-primary-soft text-foreground' : 'text-muted-foreground hover:bg-accent')}
        >
          {optionLabel(o)}
        </li>
      ))}
    </ul>,
    document.body,
  )
}
