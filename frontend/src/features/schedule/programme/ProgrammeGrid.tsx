import { useEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { ChevronDown, ChevronRight, GripVertical, Info } from 'lucide-react'
import { calendarOf, type EditableField, type ProgrammeRowView, type ProgrammeView } from '@/api/programme'
import { toDay } from '@/lib/programme'
import { formatDate, today as todayIso } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ROW_H, editableCell, type Col } from './columns'
import { daysOff, monthBands, scaleFor, ticks, xOf, type Zoom } from './gantt'

const HEAD_H = 52

const num = (n: number, blankZero = true) => (blankZero && !n ? '' : Number.isInteger(n) ? String(n) : n.toFixed(2))

/** What a cell shows. */
function shown(col: Col, r: ProgrammeRowView): string {
  switch (col.id) {
    case 'wbs': return r.wbs
    case 'start': return r.start ? formatDate(r.start) : ''
    case 'end': return r.end ? formatDate(r.end) : ''
    // a row not scheduled yet (no Start, no predecessor) still shows the Days typed for it
    case 'days': return r.days === null ? (r.summary || r.typed.days === null ? '' : String(r.typed.days)) : String(r.days)
    case 'quantity': return num(r.quantity)
    case 'labour_required': return num(r.labour_required)
    case 'percent': return r.start || r.percent ? `${Math.round(r.percent)}%` : ''
    default: return String(r[col.id] ?? '')
  }
}

/** What an editor opens with. */
function raw(col: Col, r: ProgrammeRowView): string {
  switch (col.id) {
    case 'start': return r.typed.start || r.start || ''
    case 'end': return r.end || ''
    case 'days': return r.days === null ? (r.typed.days === null ? '' : String(r.typed.days)) : String(r.days)
    case 'quantity': return r.quantity ? String(r.quantity) : ''
    case 'labour_required': return r.labour_required ? String(r.labour_required) : ''
    case 'percent': return String(Math.round(r.percent))
    default: return String(r[col.id as keyof ProgrammeRowView] ?? '')
  }
}

export interface GridProps {
  view: ProgrammeView
  rows: ProgrammeRowView[]
  columns: Col[]
  collapsed: Set<number>
  onToggle: (id: number) => void
  zoom: Zoom
  showCritical: boolean
  editable: boolean
  active: { r: number; c: number }
  setActive: (a: { r: number; c: number }) => void
  onEdit: (id: number, field: EditableField, value: string) => void
  onPaste: (r: number, c: number, block: string[][]) => void
  onIndent: (id: number) => void
  onOutdent: (id: number) => void
  onUndo: () => void
  onRedo: () => void
  onAddAfter: (id: number | null) => void
  onDelete: (id: number) => void
  onDetail: (id: number) => void
  onDrop: (dragId: number, targetId: number, asChild: boolean) => void
  height: number
}

/**
 * The programme as the office's sheet has it: the columns on the left stay put while the chart beside them scrolls
 * sideways, and only the rows in view are drawn, so a thousand rows scroll as smoothly as ten.
 */
export function ProgrammeGrid(p: GridProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  // On a phone the table is wider than the screen; frozen, its dates could never be scrolled to, so there only the SL.NO and the item stay in place while the rest scrolls with the chart.
  const [narrow, setNarrow] = useState(false)
  useEffect(() => {
    const el = scrollRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const look = () => setNarrow(el.clientWidth < 760)
    look()
    const ro = new ResizeObserver(look)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const cols = useMemo(() => (narrow ? p.columns.map((c) => (c.id === 'name' ? { ...c, w: 150 } : c.id === 'wbs' ? { ...c, w: Math.min(c.w, 58) } : c)) : p.columns), [narrow, p.columns])
  const FROZEN = 2                                           // SL.NO and the item
  const frozenW = cols.slice(0, FROZEN).reduce((s, c) => s + c.w, 0)
  const blocks: [number, number][] = [[0, FROZEN], [FROZEN, cols.length]]
  const left = cols.reduce((s, c) => s + c.w, 0)
  const todayStr = todayIso()
  const scale = useMemo(() => scaleFor(p.view.start, p.view.finish, todayStr, p.zoom), [p.view.start, p.view.finish, todayStr, p.zoom])
  const cal = useMemo(() => calendarOf(p.view), [p.view])
  const off = useMemo(() => daysOff(scale, cal, p.zoom), [scale, cal, p.zoom])
  const months = useMemo(() => monthBands(scale), [scale])
  const marks = useMemo(() => ticks(scale, p.zoom), [scale, p.zoom])
  const todayX = xOf(scale, toDay(todayStr))
  const virt = useVirtualizer({ count: p.rows.length, getScrollElement: () => scrollRef.current, estimateSize: () => ROW_H, overscan: 12, paddingStart: HEAD_H })
  const [editing, setEditing] = useState<string | null>(null)
  const [dragId, setDragId] = useState<number | null>(null)
  const [dropAt, setDropAt] = useState<number | null>(null)
  const bodyH = p.rows.length * ROW_H

  useEffect(() => {
    if (p.rows.length) virt.scrollToIndex(Math.min(p.active.r, p.rows.length - 1), { align: 'auto' })
  }, [p.active.r, p.rows.length, virt])

  const move = (dr: number, dc: number) => {
    const r = Math.max(0, Math.min(p.rows.length - 1, p.active.r + dr))
    const c = Math.max(0, Math.min(cols.length - 1, p.active.c + dc))
    p.setActive({ r, c })
  }
  const start = (initial?: string) => {
    const col = cols[p.active.c]
    const row = p.rows[p.active.r]
    if (!p.editable || !editableCell(col, row)) return
    setEditing(initial ?? raw(col, row))
  }
  const commit = (then?: [number, number]) => {
    const col = cols[p.active.c]
    const row = p.rows[p.active.r]
    if (editing !== null && row && col && editing !== raw(col, row)) p.onEdit(row.id, col.id as EditableField, editing.trim())
    setEditing(null)
    if (then) move(then[0], then[1])
    requestAnimationFrame(() => scrollRef.current?.focus())
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (editing !== null) return
    const row = p.rows[p.active.r]
    const col = cols[p.active.c]
    const ctrl = e.ctrlKey || e.metaKey
    if (ctrl && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); if (e.shiftKey) p.onRedo(); else p.onUndo(); return }
    if (ctrl && (e.key === 'y' || e.key === 'Y')) { e.preventDefault(); p.onRedo(); return }
    if (ctrl && (e.key === 'c' || e.key === 'C') && row && col) { void navigator.clipboard?.writeText(shown(col, row)); return }
    if (e.altKey && e.shiftKey && row && p.editable && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
      e.preventDefault()
      if (e.key === 'ArrowRight') p.onIndent(row.id)
      else p.onOutdent(row.id)
      return
    }
    switch (e.key) {
      case 'ArrowUp': e.preventDefault(); move(-1, 0); return
      case 'ArrowDown': e.preventDefault(); move(1, 0); return
      case 'ArrowLeft': e.preventDefault(); move(0, -1); return
      case 'ArrowRight': e.preventDefault(); move(0, 1); return
      case 'Home': e.preventDefault(); p.setActive({ r: p.active.r, c: 0 }); return
      case 'End': e.preventDefault(); p.setActive({ r: p.active.r, c: cols.length - 1 }); return
      case 'PageDown': e.preventDefault(); move(15, 0); return
      case 'PageUp': e.preventDefault(); move(-15, 0); return
      case 'Enter': case 'F2': e.preventDefault(); start(); return
      case 'Tab':
        e.preventDefault()
        // On the row number, Tab nests the row under the one above (Shift+Tab takes it out), as in the sheet.
        if (col?.id === 'wbs' && row && p.editable) { if (e.shiftKey) p.onOutdent(row.id); else p.onIndent(row.id) } else move(0, e.shiftKey ? -1 : 1)
        return
      case 'Insert': if (p.editable) { e.preventDefault(); p.onAddAfter(row?.id ?? null) } return
      case 'Delete': case 'Backspace':
        if (p.editable && row && editableCell(col, row) && col.id !== 'name') { e.preventDefault(); p.onEdit(row.id, col.id as EditableField, '') }
        return
    }
    if (e.key.length === 1 && !ctrl && !e.altKey && p.editable && editableCell(col, row) && col.kind !== 'date') {
      e.preventDefault()
      start(e.key)
    }
  }

  const onPaste = (e: React.ClipboardEvent) => {
    if (editing !== null || !p.editable) return
    const text = e.clipboardData.getData('text/plain')
    if (!text) return
    e.preventDefault()
    const lines = text.replace(/\r/g, '').split('\n')
    while (lines.length && !lines[lines.length - 1].trim()) lines.pop()
    p.onPaste(p.active.r, p.active.c, lines.map((l) => l.split('\t')))
  }

  return (
    <div
      ref={scrollRef}
      role="grid"
      aria-label="Programme"
      aria-rowcount={p.rows.length}
      tabIndex={0}
      onKeyDown={onKey}
      onPaste={onPaste}
      className="relative overflow-auto rounded-lg border border-border bg-card text-[12.5px] outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
      style={{ height: p.height }}
    >
      <div className="relative" style={{ width: left + scale.width, height: HEAD_H + bodyH }}>
        {/* days off and today, behind the bars */}
        {off.map((x) => <div key={x} aria-hidden className="absolute bg-muted/70" style={{ left: left + x, top: HEAD_H, width: scale.px, height: bodyH }} />)}
        <div aria-hidden className="absolute z-[1] w-0.5 bg-danger/70" style={{ left: left + todayX + scale.px / 2, top: HEAD_H, height: bodyH }} title="Today" />

        {/* the header */}
        <div className="sticky top-0 z-30 flex" style={{ height: HEAD_H, width: left + scale.width }}>
          {blocks.map(([a, b], blk) => (<div key={blk} className={cn('flex border-b border-r border-border bg-surface', blk === 0 ? 'z-50' : 'z-40', (blk === 0 || !narrow) && 'sticky')} style={{ width: cols.slice(a, b).reduce((s, c) => s + c.w, 0), left: blk === 0 ? 0 : frozenW }}>
            {cols.slice(a, b).map((c) => (
              <div key={c.id} role="columnheader" className={cn('flex items-end border-r border-border px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground', c.align === 'right' && 'justify-end')} style={{ width: c.w }}>{c.label}</div>
            ))}
          </div>))}
          <div className="relative border-b border-border bg-surface" style={{ width: scale.width }}>
            {months.map((m) => <div key={m.x} className="absolute top-0 h-6 truncate border-l border-border px-1.5 pt-1 text-[11px] font-semibold" style={{ left: m.x, width: m.w }}>{m.label}</div>)}
            {marks.map((t) => <div key={t.x} className="absolute bottom-0 h-6 border-l border-border/60 pt-1 text-center text-[10px] text-muted-foreground" style={{ left: t.x, width: p.zoom === 'day' ? scale.px : scale.px * 7 }}>{t.label}</div>)}
          </div>
        </div>

        {/* the rows in view */}
        {virt.getVirtualItems().map((vi) => {
          const r = p.rows[vi.index]
          const on = vi.index === p.active.r
          const s = r.start ? toDay(r.start) : null
          const e = r.end ? toDay(r.end) : null
          const overdue = !r.summary && e !== null && r.end! < todayStr && r.percent < 100
          return (
            <div
              key={r.id}
              role="row"
              aria-rowindex={vi.index + 1}
              className={cn('absolute left-0 flex border-b border-border/60', dropAt === r.id && 'border-t-2 border-t-primary')}
              style={{ top: vi.start, height: ROW_H, width: left + scale.width }}
              onDragOver={(ev) => { if (dragId !== null) { ev.preventDefault(); setDropAt(r.id) } }}
              onDragLeave={() => setDropAt((d) => (d === r.id ? null : d))}
              onDrop={(ev) => { ev.preventDefault(); if (dragId !== null && dragId !== r.id) p.onDrop(dragId, r.id, ev.altKey); setDragId(null); setDropAt(null) }}
            >
              {blocks.map(([a, b], blk) => (<div key={blk} className={cn('flex border-r border-border', blk === 0 ? 'z-30' : 'z-20', (blk === 0 || !narrow) && 'sticky', 'bg-card', on && '[background-image:linear-gradient(var(--primary-soft),var(--primary-soft))]', r.summary && 'font-semibold')} style={{ width: cols.slice(a, b).reduce((s, c) => s + c.w, 0), left: blk === 0 ? 0 : frozenW }}>
                {cols.slice(a, b).map((c, k) => {
                  const ci = a + k
                  const active = on && ci === p.active.c
                  const editable = p.editable && editableCell(c, r)
                  return (
                    <div
                      key={c.id}
                      role="gridcell"
                      aria-selected={active}
                      className={cn('relative flex items-center overflow-hidden border-r border-border/60 px-2', c.align === 'right' && 'justify-end tabular-nums', active && 'outline outline-2 -outline-offset-2 outline-primary', !editable && c.kind !== null && 'text-muted-foreground', c.id === 'wbs' && 'font-mono text-[11.5px]')}
                      style={{ width: c.w }}
                      onMouseDown={() => { if (editing !== null) commit(); p.setActive({ r: vi.index, c: ci }) }}
                      onDoubleClick={() => { p.setActive({ r: vi.index, c: ci }); if (editable) setEditing(raw(c, r)); else if (c.id === 'wbs') p.onDetail(r.id) }}
                    >
                      {active && editing !== null ? (
                        <input
                          ref={inputRef}
                          autoFocus
                          type={c.kind === 'date' ? 'date' : 'text'}
                          inputMode={c.kind === 'number' ? 'decimal' : undefined}
                          aria-label={c.label}
                          value={editing}
                          onChange={(ev) => setEditing(ev.target.value)}
                          onBlur={() => commit()}
                          onKeyDown={(ev) => {
                            if (ev.key === 'Enter') { ev.preventDefault(); commit([1, 0]) }
                            else if (ev.key === 'Tab') { ev.preventDefault(); commit([0, ev.shiftKey ? -1 : 1]) }
                            else if (ev.key === 'Escape') { ev.preventDefault(); setEditing(null); requestAnimationFrame(() => scrollRef.current?.focus()) }
                          }}
                          className="absolute inset-0 w-full bg-background px-2 text-[12.5px] outline-none"
                        />
                      ) : c.id === 'wbs' ? (
                        <span className="flex items-center gap-0.5">
                          {p.editable && (
                            <span
                              draggable
                              onDragStart={(ev) => { setDragId(r.id); ev.dataTransfer.setData('text/plain', String(r.id)); ev.dataTransfer.effectAllowed = 'move' }}
                              onDragEnd={() => { setDragId(null); setDropAt(null) }}
                              className="cursor-grab text-muted-foreground/60 hover:text-foreground"
                              title="Drag to move. Hold Alt when dropping to put it under that row."
                              aria-hidden
                            ><GripVertical className="size-3.5" /></span>
                          )}
                          {r.wbs}
                        </span>
                      ) : c.id === 'name' ? (
                        <span className="flex min-w-0 items-center gap-1" style={{ paddingLeft: r.level * 14 }}>
                          {r.summary ? (
                            <button type="button" className="-ml-1 grid size-5 shrink-0 place-items-center rounded text-muted-foreground hover:bg-accent hover:text-foreground" aria-label={p.collapsed.has(r.id) ? `Show what is under ${r.name}` : `Hide what is under ${r.name}`} aria-expanded={!p.collapsed.has(r.id)} onMouseDown={(ev) => ev.stopPropagation()} onClick={() => p.onToggle(r.id)}>
                              {p.collapsed.has(r.id) ? <ChevronRight className="size-3.5" /> : <ChevronDown className="size-3.5" />}
                            </button>
                          ) : <span className="w-4 shrink-0" />}
                          <span className={cn('truncate', r.critical && p.showCritical && !r.summary && 'text-danger')} title={r.description || r.name}>{r.name}</span>
                          <button type="button" className={cn('grid size-5 shrink-0 place-items-center rounded hover:bg-accent', r.problem ? 'text-danger' : r.description ? 'text-muted-foreground' : 'text-muted-foreground/40 hover:text-muted-foreground')} aria-label={`Details of ${r.name}`} title={r.problem || 'Full description, links, progress and settings'} onMouseDown={(ev) => ev.stopPropagation()} onClick={() => p.onDetail(r.id)}>
                            <Info className="size-3.5" />
                          </button>
                        </span>
                      ) : (
                        <span className="truncate">{shown(c, r)}</span>
                      )}
                    </div>
                  )
                })}
              </div>))}
              {/* the bar */}
              <div className="relative" style={{ width: scale.width, height: ROW_H }}>
                {s !== null && e !== null && (r.summary ? (
                  <div className="absolute top-[11px] h-[7px] bg-foreground/75" style={{ left: xOf(scale, s), width: Math.max(3, (e - s + 1) * scale.px) }} title={`${r.name}: ${formatDate(r.start!)} - ${formatDate(r.end!)}, ${r.days} days`}>
                    <span className="absolute -bottom-1 left-0 h-1.5 w-1 bg-foreground/75" />
                    <span className="absolute -bottom-1 right-0 h-1.5 w-1 bg-foreground/75" />
                  </div>
                ) : r.milestone ? (
                  <div className="absolute top-[10px] size-3 rotate-45 bg-foreground" style={{ left: xOf(scale, s) + scale.px / 2 - 6 }} title={`${r.name}: ${formatDate(r.start!)}`} />
                ) : (
                  <>
                    {r.baseline?.start && r.baseline.end && (
                      <div className="absolute top-[25px] h-[3px] rounded-full bg-muted-foreground/50" style={{ left: xOf(scale, toDay(r.baseline.start)), width: Math.max(3, (toDay(r.baseline.end) - toDay(r.baseline.start) + 1) * scale.px) }} title="Baseline" />
                    )}
                    <div
                      className={cn('absolute top-[8px] h-[15px] overflow-hidden rounded-sm', overdue ? 'bg-danger/35' : 'bg-primary/30', p.showCritical && r.critical && 'ring-2 ring-warning')}
                      style={{ left: xOf(scale, s), width: Math.max(3, (e - s + 1) * scale.px) }}
                      title={`${r.name}: ${formatDate(r.start!)} - ${formatDate(r.end!)}, ${r.days} working days, ${Math.round(r.percent)}% done${overdue ? ' - overdue' : ''}${r.critical ? ' - critical' : ''}`}
                    >
                      <div className={cn('h-full', overdue ? 'bg-danger' : 'bg-primary')} style={{ width: `${Math.min(100, r.percent)}%` }} />
                    </div>
                  </>
                ))}
              </div>
            </div>
          )
        })}
        {p.rows.length === 0 && <p className={cn('p-6 text-sm text-muted-foreground', !narrow && 'sticky left-0')} style={{ top: HEAD_H, width: left }}>Nothing here yet.</p>}
      </div>
    </div>
  )
}
