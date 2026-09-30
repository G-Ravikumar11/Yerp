import { useCallback, useEffect, useImperativeHandle, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { cn } from '@/lib/utils'
import { CellEditor, type Move } from './CellEditor'
import { buildLayout, cellId, GridRow, ROW_NUMBER_WIDTH, type Handlers } from './GridRow'
import {
  clamp,
  clearRange,
  coerce,
  editText,
  fillRange,
  getValue,
  isReadOnly,
  setValue,
  jump,
  makeRange,
  planPaste,
  rangeNumbers,
  rangeText,
  rowIsBlank,
  validateRows,
  withRows,
} from './model'
import { StatusBar } from './StatusBar'
import type { Cell, ChangeInfo, DataGridProps, Range } from './types'
import { optionLabel, optionValue, parseTSV } from './values'

interface Edit {
  r: number
  c: number
  mode: 'enter' | 'edit'
  initial: string
}

interface Selection {
  anchor: Cell
  active: Cell
}

const HISTORY_LIMIT = 100

async function writeClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    return
  } catch {
    // Not a secure page, or permission refused: fall back to the old way.
  }
  try {
    const box = document.createElement('textarea')
    box.value = text
    box.style.cssText = 'position:fixed;opacity:0;pointer-events:none'
    document.body.appendChild(box)
    box.select()
    document.execCommand('copy')
    box.remove()
  } catch {
    // Nothing more to try.
  }
}

/**
 * A spreadsheet in the page.
 *
 * It behaves the way Excel does because that is what the people using it know:
 * select a cell and type to replace it, F2 or a double click to change it in
 * place, Enter and Tab to move on, arrows to walk about, Shift to select a
 * block, Ctrl+C / X / V to and from Excel, Ctrl+Z to take it back. The sheet
 * always has one more empty row waiting under the last.
 *
 * It is controlled: it shows `rows` and reports every change through
 * `onRowsChange`, so the rows can live wherever the screen keeps them.
 */
export function DataGrid<T>({
  columns,
  rows,
  onRowsChange,
  newRow,
  isBlank,
  autoGrow = true,
  minRows = 0,
  readOnly = false,
  maxHeight = 560,
  rowHeight = 38,
  rowClassName,
  footer,
  onSelectionChange,
  className,
  emptyText = 'Nothing here yet.',
  ref,
  'aria-label': ariaLabel,
}: DataGridProps<T>) {
  const gridId = useId().replace(/:/g, '')
  const containerRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const newRowRef = useRef(newRow)
  newRowRef.current = newRow

  const [sel, setSel] = useState<Selection>({ anchor: { r: 0, c: 0 }, active: { r: 0, c: 0 } })
  const [edit, setEdit] = useState<Edit | null>(null)
  const [focused, setFocused] = useState(false)
  const [message, setMessage] = useState('')
  const editTextRef = useRef('')
  const dragging = useRef(false)
  const messageTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const blankCheck = useCallback(
    (row: T, i: number) => (isBlank ? isBlank(row, i) : rowIsBlank(columns, row, i)),
    [isBlank, columns],
  )

  /** The rows as drawn: the data, then the empty row waiting under it. */
  const viewLength = useCallback(
    (arr: readonly T[]) => {
      let n = arr.length
      if (autoGrow && (n === 0 || !blankCheck(arr[n - 1], n - 1))) n++
      return Math.max(n, minRows)
    },
    [autoGrow, minRows, blankCheck],
  )

  const view = useMemo(() => {
    const out = rows.slice()
    while (out.length < viewLength(rows)) out.push(newRowRef.current())
    return out
  }, [rows, viewLength])

  const layout = useMemo(() => buildLayout(columns), [columns])
  const errors = useMemo(() => validateRows(columns, rows), [columns, rows])
  const issueCount = useMemo(() => {
    let n = 0
    errors.forEach((e) => (n += Object.keys(e).length))
    return n
  }, [errors])
  const dataRows = useMemo(() => rows.filter((r, i) => !blankCheck(r, i)), [rows, blankCheck])
  const firstBlank = useMemo(() => view.findIndex((r, i) => blankCheck(r, i)), [view, blankCheck])

  const hasHints = columns.some((c) => c.hint)
  const headerHeight = hasHints ? 46 : 38
  const hasSummary = columns.some((c) => c.summary)
  const lastCol = columns.length - 1

  // The selection is kept as typed and clamped as drawn, so it survives the
  // rows shrinking and growing back (undo, a paste that runs off the end).
  const clampCell = (cell: Cell): Cell => ({
    r: clamp(cell.r, 0, Math.max(0, view.length - 1)),
    c: clamp(cell.c, 0, Math.max(0, lastCol)),
  })
  const active = clampCell(sel.active)
  const anchor = clampCell(sel.anchor)
  const range = makeRange(anchor, active)

  const virtualizer = useVirtualizer({
    count: view.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 8,
    scrollMargin: headerHeight,
    scrollPaddingStart: headerHeight,
    scrollPaddingEnd: hasSummary ? rowHeight : 0,
    initialRect: { width: 1000, height: maxHeight },
  })

  useEffect(() => {
    onSelectionChange?.(view.length ? range : null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range.r0, range.r1, range.c0, range.c1])

  useLayoutEffect(() => {
    if (!view.length) return
    virtualizer.scrollToIndex(active.r, { align: 'auto' })
    document.getElementById(cellId(gridId, active.r, active.c))?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active.r, active.c])

  const say = (text: string) => {
    setMessage(text)
    clearTimeout(messageTimer.current)
    messageTimer.current = setTimeout(() => setMessage(''), 4000)
  }
  useEffect(() => () => clearTimeout(messageTimer.current), [])

  /* --- History ----------------------------------------------------------- */

  const history = useRef<{ past: (readonly T[])[]; future: (readonly T[])[]; last: readonly T[] }>({
    past: [],
    future: [],
    last: rows,
  })

  const emit = (next: T[], info: ChangeInfo) => {
    const h = history.current
    if (h.last !== rows) {
      // The rows were replaced from outside (a reload): what came before is
      // not this sheet's past any more.
      h.past = []
      h.future = []
    }
    h.past.push(rows)
    if (h.past.length > HISTORY_LIMIT) h.past.shift()
    h.future = []
    h.last = next
    onRowsChange(next, info)
  }

  const undo = () => {
    const h = history.current
    if (h.last !== rows) {
      h.past = []
      h.future = []
    }
    const prev = h.past.pop()
    if (!prev) return say('Nothing to undo')
    h.future.push(rows)
    // The very array handed over is remembered, so the next undo or redo
    // knows these rows are still this sheet's own.
    const restored = prev.slice()
    h.last = restored
    onRowsChange(restored, { kind: 'undo' })
  }

  const redo = () => {
    const h = history.current
    if (h.last !== rows) {
      h.past = []
      h.future = []
    }
    const next = h.future.pop()
    if (!next) return say('Nothing to redo')
    h.past.push(rows)
    const restored = next.slice()
    h.last = restored
    onRowsChange(restored, { kind: 'redo' })
  }

  useImperativeHandle(ref, () => ({
    focus: () => containerRef.current?.focus({ preventScroll: true }),
    undo,
    redo,
    selectCell: (r, c) => setSel({ anchor: { r, c }, active: { r, c } }),
  }))

  /* --- Selecting and moving ---------------------------------------------- */

  const select = (cell: Cell, extend = false) =>
    setSel((s) => {
      const c = { r: clamp(cell.r, 0, Math.max(0, view.length - 1)), c: clamp(cell.c, 0, Math.max(0, lastCol)) }
      return extend ? { anchor: s.anchor, active: c } : { anchor: c, active: c }
    })

  const focusGrid = () => containerRef.current?.focus({ preventScroll: true })

  const moveAfterEdit = (from: Cell, move: Move, lengthAfter: number) => {
    const d = { down: [1, 0], up: [-1, 0], right: [0, 1], left: [0, -1], none: [0, 0] }[move]
    const cell = { r: clamp(from.r + d[0], 0, Math.max(0, lengthAfter - 1)), c: clamp(from.c + d[1], 0, lastCol) }
    setSel({ anchor: cell, active: cell })
  }

  /* --- Editing ----------------------------------------------------------- */

  const canEdit = (r: number, c: number) => !readOnly && r < view.length && !isReadOnly(columns[c], view[r], r)

  const startEdit = (mode: 'enter' | 'edit', typed = '') => {
    const { r, c } = active
    if (!canEdit(r, c)) return
    const col = columns[c]
    if (col.type === 'checkbox') return
    const initial = mode === 'enter' ? typed : col.type === 'select' ? '' : editText(col, view[r], r)
    editTextRef.current = initial
    setEdit({ r, c, mode, initial })
  }

  const closeEditor = () => {
    setEdit(null)
    focusGrid()
  }

  /** Returns why the value cannot be kept, or null once it has been. */
  const commit = (text: string, move: Move): string | null => {
    if (!edit) return null
    const { r, c } = edit
    const col = columns[c]
    const parsed = coerce(col, text)
    if (!parsed.ok) return parsed.error

    const current = r < rows.length ? rows[r] : newRowRef.current()
    const before = getValue(col, current, r)
    const same = Object.is(before, parsed.value) || ((before == null || before === '') && (parsed.value == null || parsed.value === ''))
    let next: T[] = rows as T[]
    if (!same) {
      next = withRows(rows, r + 1, newRowRef.current)
      next[r] = setValue(col, next[r], parsed.value)
      emit(next, { kind: 'edit', range: { r0: r, r1: r, c0: c, c1: c } })
    }
    closeEditor()
    moveAfterEdit({ r, c }, move, viewLength(next))
    return null
  }

  const cancelEdit = () => closeEditor()

  const blurAway = (text: string) => {
    const err = commit(text, 'none')
    if (err) {
      setEdit(null)
      say(`"${text}" was not kept - ${err.toLowerCase()}`)
    }
  }

  /** Whatever is in the box is kept if it can be, before the cursor goes elsewhere. */
  const settleEditor = () => {
    if (!edit) return
    const err = commit(editTextRef.current, 'none')
    if (err) {
      setEdit(null)
      say(`"${editTextRef.current}" was not kept - ${err.toLowerCase()}`)
    }
  }

  const apply = (next: T[], info: ChangeInfo, note?: string) => {
    emit(next, info)
    if (note) say(note)
  }

  const toggle = (r: number, c: number) => {
    if (!canEdit(r, c)) return
    const col = columns[c]
    const next = withRows(rows, r + 1, newRowRef.current)
    next[r] = setValue(col, next[r], !getValue(col, next[r], r))
    apply(next, { kind: 'edit', range: { r0: r, r1: r, c0: c, c1: c } })
  }

  const clearSelection = (kind: 'clear' | 'cut' = 'clear') => {
    if (readOnly) return
    apply(clearRange(columns, rows, range), { kind, range })
  }

  const cellsIn = (rg: Range) => (rg.r1 - rg.r0 + 1) * (rg.c1 - rg.c0 + 1)

  const copySelection = async (cut: boolean) => {
    await writeClipboard(rangeText(columns, view, range))
    say(`${cut ? 'Cut' : 'Copied'} ${cellsIn(range)} cell${cellsIn(range) === 1 ? '' : 's'}`)
    if (cut) clearSelection('cut')
    focusGrid()
  }

  const onPaste = (e: React.ClipboardEvent) => {
    // Inside the cell box the browser's own paste is right.
    if (edit || (e.target as HTMLElement).tagName === 'INPUT' || readOnly) return
    const text = e.clipboardData.getData('text/plain')
    if (!text) return
    e.preventDefault()
    const result = planPaste(columns, rows, parseTSV(text), range, newRowRef.current)
    if (!result) return
    emit(result.rows, { kind: 'paste', range: result.range })
    setSel({ anchor: { r: result.range.r0, c: result.range.c0 }, active: { r: result.range.r1, c: result.range.c1 } })
    say(
      `${result.pasted} cell${result.pasted === 1 ? '' : 's'} pasted` +
        (result.added ? `, ${result.added} row${result.added === 1 ? '' : 's'} added` : '') +
        (result.skipped ? `, ${result.skipped} left alone (computed, or not a valid entry)` : ''),
    )
  }

  const removeRows = () => {
    if (readOnly || range.r0 >= rows.length) return
    const next = rows.filter((_, i) => i < range.r0 || i > range.r1)
    apply(next, { kind: 'delete', range }, `${Math.min(range.r1, rows.length - 1) - range.r0 + 1} row(s) removed`)
    setSel((s) => ({ anchor: { r: range.r0, c: s.anchor.c }, active: { r: range.r0, c: s.active.c } }))
  }

  const insertRows = () => {
    if (readOnly) return
    const count = range.r1 - range.r0 + 1
    const next = rows.slice()
    const at = Math.min(range.r0, next.length)
    next.splice(at, 0, ...Array.from({ length: count }, () => newRowRef.current()))
    apply(next, { kind: 'insert', range })
  }

  const nextIssue = () => {
    const order = [...errors.keys()].sort((a, b) => a - b)
    const flat: Cell[] = []
    for (const r of order) for (const id of Object.keys(errors.get(r)!)) flat.push({ r, c: columns.findIndex((c) => c.id === id) })
    if (!flat.length) return
    const after = flat.find((f) => f.r > active.r || (f.r === active.r && f.c > active.c)) ?? flat[0]
    select(after)
    focusGrid()
  }

  /* --- Keyboard ---------------------------------------------------------- */

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (edit || e.nativeEvent.isComposing || !view.length) return
    if (e.target !== e.currentTarget) return
    const mod = e.ctrlKey || e.metaKey
    const key = e.key
    const lastRow = view.length - 1
    const dir: Record<string, [number, number]> = { ArrowDown: [1, 0], ArrowUp: [-1, 0], ArrowRight: [0, 1], ArrowLeft: [0, -1] }
    const page = Math.max(1, Math.floor(maxHeight / rowHeight) - 1)
    let handled = true

    if (e.altKey && key === 'ArrowDown') {
      startEdit('edit')
    } else if (dir[key]) {
      const [dr, dc] = dir[key]
      select(mod ? jump(columns, view, active, dr, dc, view.length) : { r: active.r + dr, c: active.c + dc }, e.shiftKey)
    } else if (key === 'Tab') {
      const next = e.shiftKey
        ? active.c > 0
          ? { r: active.r, c: active.c - 1 }
          : active.r > 0
            ? { r: active.r - 1, c: lastCol }
            : null
        : active.c < lastCol
          ? { r: active.r, c: active.c + 1 }
          : active.r < lastRow
            ? { r: active.r + 1, c: 0 }
            : null
      // Off either end, Tab carries on out of the sheet rather than trapping the keyboard.
      if (next) select(next)
      else handled = false
    } else if (key === 'Enter') {
      select({ r: active.r + (e.shiftKey ? -1 : 1), c: active.c })
    } else if (key === 'Home') {
      select(mod ? { r: 0, c: 0 } : { r: active.r, c: 0 }, e.shiftKey)
    } else if (key === 'End') {
      select(mod ? { r: Math.max(0, rows.length - 1), c: lastCol } : { r: active.r, c: lastCol }, e.shiftKey)
    } else if (key === 'PageDown' || key === 'PageUp') {
      select({ r: active.r + (key === 'PageDown' ? page : -page), c: active.c }, e.shiftKey)
    } else if (key === 'F2') {
      startEdit('edit')
    } else if (key === 'Delete' || key === 'Backspace') {
      clearSelection()
    } else if (key === 'Escape') {
      select(active)
    } else if (mod && key.toLowerCase() === 'a') {
      setSel({ anchor: { r: 0, c: 0 }, active: { r: lastRow, c: lastCol } })
    } else if (mod && key.toLowerCase() === 'c') {
      void copySelection(false)
    } else if (mod && key.toLowerCase() === 'x') {
      if (readOnly) handled = false
      else void copySelection(true)
    } else if (mod && key.toLowerCase() === 'v') {
      handled = false // the browser's paste event does the work
    } else if (mod && key.toLowerCase() === 'z') {
      if (readOnly) handled = false
      else if (e.shiftKey) redo()
      else undo()
    } else if (mod && key.toLowerCase() === 'y') {
      if (readOnly) handled = false
      else redo()
    } else if (mod && (key.toLowerCase() === 'd' || key.toLowerCase() === 'r')) {
      if (!readOnly) apply(fillRange(columns, rows, range, key.toLowerCase() === 'd' ? 'down' : 'right'), { kind: 'fill', range })
    } else if (mod && key === '-') {
      removeRows()
    } else if (mod && (key === '+' || (key === '=' && e.shiftKey))) {
      insertRows()
    } else if (key === ' ' && (e.shiftKey || mod)) {
      if (e.shiftKey && !mod) setSel({ anchor: { r: active.r, c: 0 }, active: { r: active.r, c: lastCol } })
      else setSel({ anchor: { r: 0, c: active.c }, active: { r: lastRow, c: active.c } })
    } else if (key === ' ' && columns[active.c]?.type === 'checkbox') {
      toggle(active.r, active.c)
    } else if (key === ' ' && columns[active.c]?.type === 'select') {
      startEdit('edit')
    } else if (!mod && !e.altKey && (key.length === 1 || key === 'Process')) {
      // Typing on a selected cell replaces what is in it. An input method
      // (Telugu, Hindi) reports "Process": open the box and let it compose there.
      startEdit('enter', key === 'Process' ? '' : key)
    } else handled = false

    if (handled) e.preventDefault()
  }

  /* --- Mouse ------------------------------------------------------------- */

  const handlers = useRef<Handlers>(undefined as unknown as Handlers)
  handlers.current = {
    cellDown: (r, c, e) => {
      if (e.button !== 0) return
      settleEditor()
      e.preventDefault()
      focusGrid()
      dragging.current = true
      select({ r, c }, e.shiftKey)
    },
    cellEnter: (r, c) => {
      if (dragging.current) select({ r, c }, true)
    },
    cellDouble: (r, c) => {
      select({ r, c })
      startEditAt(r, c)
    },
    rowHeaderDown: (r, e) => {
      settleEditor()
      e.preventDefault()
      focusGrid()
      setSel((s) => ({ anchor: e.shiftKey ? s.anchor : { r, c: 0 }, active: { r, c: lastCol } }))
    },
    toggle,
  }

  const startEditAt = (r: number, c: number) => {
    if (!canEdit(r, c)) return
    const col = columns[c]
    if (col.type === 'checkbox') return toggle(r, c)
    const initial = col.type === 'select' ? '' : editText(col, view[r], r)
    editTextRef.current = initial
    setEdit({ r, c, mode: 'edit', initial })
  }

  const stable = useMemo<Handlers>(
    () => ({
      cellDown: (...a) => handlers.current.cellDown(...a),
      cellEnter: (...a) => handlers.current.cellEnter(...a),
      cellDouble: (...a) => handlers.current.cellDouble(...a),
      rowHeaderDown: (...a) => handlers.current.rowHeaderDown(...a),
      toggle: (...a) => handlers.current.toggle(...a),
    }),
    [],
  )

  useEffect(() => {
    const up = () => (dragging.current = false)
    window.addEventListener('mouseup', up)
    return () => window.removeEventListener('mouseup', up)
  }, [])

  const onHeaderDown = (c: number, e: React.MouseEvent) => {
    settleEditor()
    e.preventDefault()
    focusGrid()
    setSel((s) => ({ anchor: e.shiftKey ? { r: 0, c: s.anchor.c } : { r: 0, c }, active: { r: Math.max(0, view.length - 1), c } }))
  }

  /* --- Drawing ----------------------------------------------------------- */

  const numbers = range.r0 !== range.r1 || range.c0 !== range.c1 ? rangeNumbers(columns, view, range) : []
  const editor =
    edit && columns[edit.c] ? (
      <CellEditor
        key={`${edit.r}:${edit.c}`}
        column={columns[edit.c]}
        initial={edit.initial}
        mode={edit.mode}
        currentLabel={
          columns[edit.c].type === 'select'
            ? (() => {
                const v = getValue(columns[edit.c], view[edit.r], edit.r)
                const o = columns[edit.c].options?.find((x) => optionValue(x) === String(v))
                return o ? optionLabel(o) : ''
              })()
            : undefined
        }
        onTextChange={(t) => (editTextRef.current = t)}
        onCommit={commit}
        onCancel={cancelEdit}
        onBlurAway={blurAway}
      />
    ) : null

  const summaries = useMemo(
    () =>
      columns.map((col) => {
        if (!col.summary) return ''
        if (typeof col.summary === 'function') return col.summary(dataRows)
        const total = dataRows.reduce((sum, row, i) => {
          const v = getValue(col, row, i)
          return sum + (typeof v === 'number' && Number.isFinite(v) ? v : 0)
        }, 0)
        return col.format
          ? col.format(total, dataRows[0] as T, 0)
          : total.toLocaleString('en-IN', { minimumFractionDigits: col.decimals ?? 0, maximumFractionDigits: col.decimals ?? 3 })
      }),
    [columns, dataRows],
  )

  const items = virtualizer.getVirtualItems()

  return (
    <div
      ref={containerRef}
      role="grid"
      tabIndex={0}
      aria-label={ariaLabel}
      aria-rowcount={view.length + 1}
      aria-colcount={columns.length + 1}
      aria-multiselectable
      aria-readonly={readOnly || undefined}
      aria-activedescendant={cellId(gridId, active.r, active.c)}
      onKeyDown={onKeyDown}
      onPaste={onPaste}
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false)
      }}
      className={cn('flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-card outline-none', 'focus-visible:border-ring focus-visible:ring-4 focus-visible:ring-ring/15', className)}
    >
      <div
        ref={scrollRef}
        className="relative overflow-auto overscroll-contain"
        style={{ maxHeight, scrollPaddingLeft: layout.pinned, scrollPaddingTop: headerHeight }}
      >
        <div style={{ width: layout.total, minWidth: '100%' }}>
          <div role="row" aria-rowindex={1} className="sticky top-0 z-20 flex bg-surface" style={{ height: headerHeight, width: layout.total }}>
            <div
              role="columnheader"
              onMouseDown={(e) => {
                e.preventDefault()
                focusGrid()
                setSel({ anchor: { r: 0, c: 0 }, active: { r: Math.max(0, view.length - 1), c: lastCol } })
              }}
              style={{ width: ROW_NUMBER_WIDTH }}
              className="sticky left-0 z-10 shrink-0 border-b border-r border-border bg-surface"
              aria-label="Select all"
            />
            {columns.map((col, c) => {
              const pin = layout.pinLeft[c]
              const right = (col.align ?? (col.type === 'number' ? 'right' : 'left')) === 'right'
              const inSelection = c >= range.c0 && c <= range.c1
              return (
                <div
                  key={col.id}
                  role="columnheader"
                  aria-colindex={c + 2}
                  onMouseDown={(e) => onHeaderDown(c, e)}
                  style={{ width: layout.widths[c], left: pin ?? undefined }}
                  className={cn(
                    'flex shrink-0 select-none flex-col justify-center border-b border-r border-border bg-surface px-2.5',
                    right && 'items-end text-right',
                    pin !== null && 'sticky z-10',
                    inSelection && focused && 'bg-select',
                  )}
                >
                  <span className="truncate text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {col.header}
                    {col.required && <span className="ml-0.5 text-danger">*</span>}
                  </span>
                  {col.hint && <span className="truncate text-[11px] font-normal normal-case text-subtle">{col.hint}</span>}
                </div>
              )
            })}
          </div>

          <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
            {items.map((v) => {
              const r = v.index
              const inRows = r >= range.r0 && r <= range.r1
              const wholeRow = inRows && range.c0 === 0 && range.c1 === lastCol
              return (
                <GridRow
                  key={r}
                  gridId={gridId}
                  row={view[r]}
                  index={r}
                  columns={columns}
                  layout={layout}
                  top={v.start - headerHeight}
                  height={rowHeight}
                  activeC={active.r === r ? active.c : -1}
                  rc0={inRows ? range.c0 : -1}
                  rc1={inRows ? range.c1 : -1}
                  rowSelected={wholeRow && focused}
                  editC={edit?.r === r ? edit.c : -1}
                  editor={edit?.r === r ? editor : undefined}
                  focused={focused}
                  errors={errors.get(r)}
                  blank={blankCheck(view[r], r)}
                  promptRow={r === firstBlank}
                  className={rowClassName?.(view[r], r)}
                  handlers={stable}
                />
              )
            })}
            {!view.length && <p className="absolute inset-x-0 top-6 text-center text-sm text-muted-foreground">{emptyText}</p>}
          </div>

          {hasSummary && (
            <div role="row" aria-rowindex={view.length + 2} className="sticky bottom-0 z-20 flex border-t border-border bg-surface font-semibold" style={{ height: rowHeight, width: layout.total }}>
              <div style={{ width: ROW_NUMBER_WIDTH }} className="sticky left-0 z-10 flex shrink-0 items-center justify-end border-r border-border bg-surface pr-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                Total
              </div>
              {columns.map((col, c) => (
                <div
                  key={col.id}
                  role="gridcell"
                  style={{ width: layout.widths[c], left: layout.pinLeft[c] ?? undefined }}
                  className={cn('flex shrink-0 items-center border-r border-border px-2.5 text-[13px] tabular', layout.pinLeft[c] !== null && 'sticky z-10 bg-surface', (col.align ?? (col.type === 'number' ? 'right' : 'left')) === 'right' && 'justify-end')}
                >
                  {summaries[c]}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <StatusBar
        rowCount={dataRows.length}
        issueCount={issueCount}
        onIssues={nextIssue}
        message={message}
        selection={numbers}
        cells={cellsIn(range)}
        footer={footer}
        readOnly={readOnly}
      />
    </div>
  )
}
