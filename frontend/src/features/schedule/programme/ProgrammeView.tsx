import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Bookmark, CalendarDays, ChevronsDownUp, ChevronsUpDown, Copy, CopyPlus, Columns3, IndentDecrease, IndentIncrease, ListPlus, ListTree, Plus, Redo2, Trash2, Undo2, Zap } from 'lucide-react'
import { Button, ConfirmDialog, Skeleton, Tabs, Tooltip } from '@/components/ui'
import {
  addHoliday, addPublicHolidays, addRows, saveBaseline, copyUnits, deleteRow, duplicateRow, editRows, moveRow, programmeKeys, recompute, removeHoliday,
  restoreProgramme, setCalendar, snapshotOf, useProgramme, type EditableField, type ProgrammeRowView, type ProgrammeView as View, type RowChange, type Snapshot,
} from '@/api/programme'
import { ApiError } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { useSession } from '@/lib/session'
import { toast } from '@/stores/toast'
import { COLUMNS, editableCell } from './columns'
import { ProgrammeGrid } from './ProgrammeGrid'
import { BoqPickerModal } from './BoqPickerModal'
import { BaselineModal, CalendarModal, CopyUnitsModal, RowDetailModal } from './ProgrammeModals'
import type { Zoom } from './gantt'

const FIELD_OF: Record<string, EditableField> = { boq_ref: 'boq_ref', name: 'name', start: 'start', end: 'end', days: 'days', uom: 'uom', quantity: 'quantity', labour_required: 'labour_required', predecessors: 'predecessors' }

/** The rows shown: everything except what is under a hidden heading, at any depth. */
function shownRows(rows: ProgrammeRowView[], collapsed: Set<number>) {
  const hidden = new Set<number>()
  const out: ProgrammeRowView[] = []
  for (const r of rows) {
    if (r.parent_id !== null && (hidden.has(r.parent_id) || collapsed.has(r.parent_id))) { hidden.add(r.id); continue }
    out.push(r)
  }
  return out
}

function loadCollapsed(job: number): Set<number> {
  try {
    return new Set(JSON.parse(localStorage.getItem(`yerp-programme-collapsed-${job}`) || '[]') as number[])
  } catch {
    return new Set()
  }
}

/**
 * Planning & Progress as the office's Excel schedule: SL.NO, BOQ Ref, the item, Start, End, working days, unit,
 * quantity, labour, predecessor and % done, with the chart beside them. Everything is worked out from the same rules
 * the server uses; what is typed shows at once and is saved. Mounted once per project (keyed by it), so nothing
 * carries over from one project's programme to the next.
 */
export function ProgrammeView({ job }: { job: number }) {
  const { can } = useSession()
  const editable = can('workorders.manage')
  const qc = useQueryClient()
  const q = useProgramme(job)
  const v = q.data
  const [zoom, setZoom] = useState<Zoom>('week')
  const [critical, setCritical] = useState(false)
  const [compact, setCompact] = useState(() => typeof window !== 'undefined' && window.innerWidth < 1600)
  const [collapsed, setCollapsed] = useState<Set<number>>(() => loadCollapsed(job))
  const [active, setActive] = useState({ r: 0, c: 2 })
  const undo = useRef<Snapshot[]>([])
  const redo = useRef<Snapshot[]>([])
  const [depth, setDepth] = useState({ undo: 0, redo: 0 })
  const counted = () => setDepth({ undo: undo.current.length, redo: redo.current.length })
  const [busy, setBusy] = useState(false)
  const [deleting, setDeleting] = useState<ProgrammeRowView | null>(null)
  const [copying, setCopying] = useState<ProgrammeRowView | null>(null)
  const [calendarOpen, setCalendarOpen] = useState(false)
  const [picking, setPicking] = useState(false)
  const [baselining, setBaselining] = useState(false)
  const [detail, setDetail] = useState<number | null>(null)

  useEffect(() => {
    try { localStorage.setItem(`yerp-programme-collapsed-${job}`, JSON.stringify([...collapsed])) } catch { /* not kept */ }
  }, [collapsed, job])

  // SL.NO as wide as the deepest number needs (1.1.2.1 is wider than 1)
  const wbsWidth = useMemo(() => Math.max(70, 34 + 7 * Math.max(0, ...(v?.rows ?? []).map((r) => r.wbs.length))), [v])
  const columns = useMemo(() => COLUMNS.filter((c) => !compact || !c.extra).map((c) => (c.id === 'wbs' ? { ...c, w: wbsWidth } : c)), [compact, wbsWidth])
  const visible = useMemo(() => (v ? shownRows(v.rows, collapsed) : []), [v, collapsed])
  const current = visible[Math.min(active.r, Math.max(0, visible.length - 1))]
  const byId = useMemo(() => new Map((v?.rows ?? []).map((r) => [r.id, r])), [v])
  // the baseline's finish against today's, in calendar days as the header counts them
  const baseFinish = useMemo(() => (v?.baseline ? v.rows.filter((r) => r.level === 0 && r.baseline?.end).map((r) => r.baseline!.end!).sort().pop() ?? null : null), [v])
  const slip = baseFinish && v?.finish ? Math.round((Date.parse(v.finish) - Date.parse(baseFinish)) / 86_400_000) : 0

  const put = (next: View) => qc.setQueryData(programmeKeys.one(job), next)
  /** The cards, the curve and the day plan read the same rows, so they are fetched again after a change. */
  const refreshOthers = () => void qc.invalidateQueries({ queryKey: ['schedule'], predicate: (x) => x.queryKey[1] !== 'programme' })
  const say = (e: unknown) => toast.error(e instanceof ApiError ? e.message : 'Something went wrong. Try again.')

  /** Every change: what it was before is kept for undo; a refusal puts the screen back as it was. */
  async function change(run: () => Promise<View>, optimistic?: View) {
    if (!v) return undefined
    const before = v
    const snap = snapshotOf(v)
    if (optimistic) put(optimistic)
    setBusy(true)
    try {
      const next = await run()
      put(next)
      refreshOthers()
      undo.current.push(snap)
      if (undo.current.length > 60) undo.current.shift()
      redo.current = []
      counted()
      if (next.message) toast.success(next.message)
      return next
    } catch (e) {
      put(before)
      say(e)
      return undefined
    } finally {
      setBusy(false)
    }
  }
  async function travel(from: React.MutableRefObject<Snapshot[]>, to: React.MutableRefObject<Snapshot[]>) {
    const snap = from.current.pop()
    if (!snap || !v) return
    const now = snapshotOf(v)
    setBusy(true)
    try {
      put(await restoreProgramme(job, snap))
      refreshOthers()
      to.current.push(now)
    } catch (e) {
      from.current.push(snap)
      say(e)
    } finally {
      setBusy(false)
      counted()
    }
  }
  const doUndo = () => void travel(undo, redo)
  const doRedo = () => void travel(redo, undo)

  const focusRow = (id: number | undefined, next?: View) => {
    if (!id) return
    const i = shownRows(next?.rows ?? v?.rows ?? [], collapsed).findIndex((r) => r.id === id)
    if (i >= 0) setActive((a) => ({ r: i, c: a.c }))
  }

  const onEdit = (id: number, field: EditableField, value: string) => {
    if (!v) return
    const ch: RowChange = { id, [field]: value }
    void change(() => editRows(job, [ch]), recompute(v, ch))
  }

  /** A block copied from Excel: across the cells from the one selected; lines past the last row become new rows. */
  const onPaste = (r0: number, c0: number, block: string[][]) => {
    if (!v) return
    const changes = new Map<number, RowChange>()
    const fresh: Record<string, unknown>[] = []
    block.forEach((cells, i) => {
      const row = visible[r0 + i]
      const values: Record<string, unknown> = {}
      cells.forEach((cell, j) => {
        const col = columns[c0 + j]
        const field = col && FIELD_OF[col.id]
        if (!field) return
        if (row && !editableCell(col, row)) return
        values[field] = cell.trim()
      })
      if (!Object.keys(values).length) return
      if (row) changes.set(row.id, { ...(changes.get(row.id) ?? { id: row.id }), ...values })
      else fresh.push({ name: 'New activity', ...values })
    })
    if (!changes.size && !fresh.length) return
    const last = visible[visible.length - 1]
    void change(async () => {
      let out: View | undefined
      if (changes.size) out = await editRows(job, [...changes.values()])
      if (fresh.length) out = await addRows(job, last?.id ?? null, last ? 'after' : 'end', fresh)
      return out!
    })
  }

  const siblings = (parent: number | null) => (v?.rows ?? []).filter((r) => r.parent_id === parent).sort((a, b) => a.order - b.order || a.id - b.id)
  const indent = (id: number) => {
    const r = byId.get(id)
    if (!r) return
    const sibs = siblings(r.parent_id)
    const prev = sibs[sibs.findIndex((s) => s.id === id) - 1]
    if (!prev) return toast.info('There is no row above at the same level to go under.')
    setCollapsed((c) => { const n = new Set(c); n.delete(prev.id); return n })
    void change(() => moveRow(job, id, prev.id, null)).then((next) => focusRow(id, next))
  }
  const outdent = (id: number) => {
    const r = byId.get(id)
    if (!r || r.parent_id === null) return toast.info('It is already at the top level.')
    const parent = byId.get(r.parent_id)!
    const sibs = siblings(parent.parent_id)
    const after = sibs[sibs.findIndex((s) => s.id === parent.id) + 1]
    void change(() => moveRow(job, id, parent.parent_id, after?.id ?? null)).then((next) => focusRow(id, next))
  }
  const addAfter = (id: number | null) => void change(() => addRows(job, id, id ? 'after' : 'end', [{ name: 'New activity' }])).then((next) => focusRow(next?.made?.[0], next))
  const addChild = (id: number) => {
    setCollapsed((c) => { const n = new Set(c); n.delete(id); return n })
    void change(() => addRows(job, id, 'child', [{ name: 'New sub-item' }])).then((next) => focusRow(next?.made?.[0], next))
  }
  const onDrop = (dragId: number, targetId: number, asChild: boolean) => {
    const t = byId.get(targetId)
    if (!t) return
    void change(() => (asChild ? moveRow(job, dragId, targetId, null) : moveRow(job, dragId, t.parent_id, targetId))).then((next) => focusRow(dragId, next))
  }
  const under = (id: number) => {
    let n = 0
    const walk = (p: number) => (v?.rows ?? []).filter((r) => r.parent_id === p).forEach((r) => { n++; walk(r.id) })
    walk(id)
    return n
  }

  if (q.isPending) return <Skeleton className="h-96 w-full" />
  if (!v) return <p className="text-sm text-danger">The programme could not be read. Try again.</p>
  const detailRow = detail !== null ? byId.get(detail) : undefined

  return (
    <section aria-label="Programme" className="grid gap-3">
      {/* the sheet's header block */}
      <div className="grid gap-x-6 gap-y-1 rounded-lg border border-border bg-card px-4 py-3 text-sm sm:grid-cols-[1fr_auto]">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{v.company || 'Schedule'} · Schedule</p>
          <p className="text-base font-semibold">{v.job.number} {v.job.name}</p>
          {v.job.location && <p className="text-muted-foreground">Location: {v.job.location}</p>}
        </div>
        <div className="text-right">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground" title="Calendar days from the first Start to the last End, both counted, as on the sheet">Time duration in days</p>
          <p className="text-2xl font-semibold tabular-nums">{v.duration || '-'}</p>
          <p className="text-xs text-muted-foreground">{v.start ? `${formatDate(v.start)} to ${formatDate(v.finish!)}` : 'No dates yet'}{v.calendar.calendar_days ? ' · calendar days' : ''}</p>
          {baseFinish && (
            <p className={`text-xs ${slip > 0 ? 'text-danger' : 'text-muted-foreground'}`} title={`Baseline "${v.baseline!.label}" saved ${formatDate(v.baseline!.saved_at.slice(0, 10))}`}>
              Baseline finish {formatDate(baseFinish)}{slip > 0 ? `, now ${slip} day${slip === 1 ? '' : 's'} later` : slip < 0 ? `, now ${-slip} day${slip === -1 ? '' : 's'} earlier` : ', on it'}
            </p>
          )}
        </div>
      </div>

      {/* the toolbar */}
      <div className="flex flex-wrap items-center gap-1.5" role="toolbar" aria-label="Programme tools">
        {editable && <>
          <Tooltip content="Add a row below the selected one (Insert)"><Button size="sm" onClick={() => addAfter(current?.id ?? null)} disabled={busy}><Plus /> Row</Button></Tooltip>
          <Tooltip content="Add a sub-item under the selected row"><Button size="sm" variant="outline" onClick={() => current && addChild(current.id)} disabled={busy || !current}><ListPlus /> Sub-item</Button></Tooltip>
          <Tooltip content="Put it under the row above (Tab on SL.NO, or Alt+Shift+Right)"><Button size="icon-sm" variant="outline" aria-label="Indent" onClick={() => current && indent(current.id)} disabled={busy || !current}><IndentIncrease /></Button></Tooltip>
          <Tooltip content="Take it out a level (Shift+Tab on SL.NO, or Alt+Shift+Left)"><Button size="icon-sm" variant="outline" aria-label="Outdent" onClick={() => current && outdent(current.id)} disabled={busy || !current}><IndentDecrease /></Button></Tooltip>
          <Tooltip content="Duplicate the row with everything under it"><Button size="icon-sm" variant="outline" aria-label="Duplicate" onClick={() => current && void change(() => duplicateRow(job, current.id))} disabled={busy || !current}><Copy /></Button></Tooltip>
          <Tooltip content="Delete the row with everything under it"><Button size="icon-sm" variant="outline" aria-label="Delete" className="text-danger" onClick={() => current && setDeleting(current)} disabled={busy || !current}><Trash2 /></Button></Tooltip>
          <span className="mx-1 h-6 w-px bg-border" />
          <Tooltip content="Undo (Ctrl+Z)"><Button size="icon-sm" variant="ghost" aria-label="Undo" onClick={doUndo} disabled={busy || !depth.undo}><Undo2 /></Button></Tooltip>
          <Tooltip content="Redo (Ctrl+Y)"><Button size="icon-sm" variant="ghost" aria-label="Redo" onClick={doRedo} disabled={busy || !depth.redo}><Redo2 /></Button></Tooltip>
          <span className="mx-1 h-6 w-px bg-border" />
          <Tooltip content="The same activities for other units, from their own start dates"><Button size="sm" variant="outline" onClick={() => current && setCopying(current)} disabled={busy || !current}><CopyPlus /> Copy to other units</Button></Tooltip>
          <Tooltip content="Keep the programme as it stands now: planned % is measured against it, and each row shows how far it has slipped from it"><Button size="sm" variant="outline" onClick={() => setBaselining(true)} disabled={busy || !v.rows.length}><Bookmark /> Save baseline</Button></Tooltip>
          <Tooltip content="Pick BOQ lines to put on the programme, after the selected row"><Button size="sm" variant="outline" onClick={() => setPicking(true)} disabled={busy}><ListTree /> Draw from BOQ</Button></Tooltip>
        </>}
        <Tooltip content="Show everything"><Button size="icon-sm" variant="ghost" aria-label="Expand all" onClick={() => setCollapsed(new Set())}><ChevronsUpDown /></Button></Tooltip>
        <Tooltip content="Show the top level only"><Button size="icon-sm" variant="ghost" aria-label="Collapse all" onClick={() => setCollapsed(new Set(v.rows.filter((r) => r.summary).map((r) => r.id)))}><ChevronsDownUp /></Button></Tooltip>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <Tooltip content="The rows with no slack: one day late on any of them is a day late at the end"><Button size="sm" variant={critical ? 'soft' : 'ghost'} aria-pressed={critical} onClick={() => setCritical((c) => !c)}><Zap /> Critical path</Button></Tooltip>
          <Tooltip content="Working days and holidays"><Button size="sm" variant="ghost" onClick={() => setCalendarOpen(true)}><CalendarDays /> Calendar</Button></Tooltip>
          <Tooltip content={compact ? 'Show BOQ Ref, U.O.M, Quantity and Labour' : 'Hide some columns to give the chart room'}><Button size="icon-sm" variant="ghost" aria-label="Columns" aria-pressed={!compact} onClick={() => setCompact((c) => !c)}><Columns3 /></Button></Tooltip>
          <div className="w-52"><Tabs label="Zoom" size="md" value={zoom} onChange={setZoom} items={[{ value: 'day', label: 'Day' }, { value: 'week', label: 'Week' }, { value: 'month', label: 'Month' }]} /></div>
        </div>
      </div>

      {v.errors.length > 0 && (
        <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-[13px] text-danger">{v.errors.map((e) => <p key={e}>{e}</p>)}</div>
      )}

      {v.rows.length === 0 ? (
        <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">
          No programme yet. {editable ? 'Add a row, draw it from the BOQ, or import a programme sheet.' : 'Someone who manages work orders can set it up.'}
        </p>
      ) : <ProgrammeGrid
        view={v}
        rows={visible}
        columns={columns}
        collapsed={collapsed}
        onToggle={(id) => setCollapsed((c) => { const n = new Set(c); if (n.has(id)) n.delete(id); else n.add(id); return n })}
        zoom={zoom}
        showCritical={critical}
        editable={editable && !busy}
        active={{ r: Math.min(active.r, Math.max(0, visible.length - 1)), c: Math.min(active.c, columns.length - 1) }}
        setActive={setActive}
        onEdit={onEdit}
        onPaste={onPaste}
        onIndent={indent}
        onOutdent={outdent}
        onUndo={doUndo}
        onRedo={doRedo}
        onAddAfter={addAfter}
        onDelete={(id) => setDeleting(byId.get(id) ?? null)}
        onDetail={setDetail}
        onDrop={onDrop}
        height={Math.min(720, Math.max(200, 64 + visible.length * 32))}
      />}
      <p className="text-xs text-muted-foreground">
        {v.rows.length} rows · Days are working days{v.calendar.calendar_days ? ' (calendar days counted)' : `; ${v.calendar.weekly_off.map((d) => ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d - 1]).join(', ') || 'no day'} off${v.calendar.holidays.length ? ` and ${v.calendar.holidays.length} holiday${v.calendar.holidays.length === 1 ? '' : 's'}` : ''}`}.
        {editable && ' Double-click or type to edit; Enter and Tab move on; paste a block straight from Excel.'}
      </p>

      <ConfirmDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)} tone="danger" confirmLabel="Delete"
        title={deleting ? `Delete ${deleting.wbs} ${deleting.name}?` : ''}
        description={deleting ? `${under(deleting.id) ? `The ${under(deleting.id)} row${under(deleting.id) === 1 ? '' : 's'} under it go too, ` : 'It goes '}with links to it and its day tasks and progress. Undo brings the rows back, not their day tasks.` : ''}
        onConfirm={async () => { const d = deleting; setDeleting(null); if (d) await change(() => deleteRow(job, d.id)) }} />
      {copying && <CopyUnitsModal open source={copying} onClose={() => setCopying(null)} onCopy={(targets) => change(() => copyUnits(job, copying.id, targets))} />}
      {calendarOpen && <CalendarModal open view={v} editable={editable} onClose={() => setCalendarOpen(false)}
        onSave={(cd, off) => change(() => setCalendar(job, cd, off))}
        onAddHoliday={(d, n) => change(() => addHoliday(job, d, n))}
        onRemoveHoliday={(h) => change(() => removeHoliday(job, h.id))}
        onPublic={(y) => change(() => addPublicHolidays(job, y))} />}
      {picking && <BoqPickerModal job={job} anchor={current?.id ?? null} onClose={() => setPicking(false)} />}
      {baselining && <BaselineModal onClose={() => setBaselining(false)} hasOne={!!v.baseline} onSave={(label) => change(() => saveBaseline(job, label))} />}
      {detailRow && <RowDetailModal key={detailRow.id} row={detailRow} editable={editable} onClose={() => setDetail(null)} onSave={(ch) => change(() => editRows(job, [ch]), recompute(v, ch))} />}
    </section>
  )
}
