import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import type { Holiday, ProgrammeRowView, ProgrammeView, RowChange } from '@/api/programme'
import { formatDate, today } from '@/lib/format'

const WEEKDAYS = [[1, 'Mon'], [2, 'Tue'], [3, 'Wed'], [4, 'Thu'], [5, 'Fri'], [6, 'Sat'], [7, 'Sun']] as const

// Each of these is mounted only while it is open, so what it starts with is read fresh every time.

/** "Copy to other units": the same set of activities for A-18, B-23 ... each from its own start, or moved by days. */
export function CopyUnitsModal({ open, source, onClose, onCopy }: { open: boolean; source: ProgrammeRowView | null; onClose: () => void; onCopy: (targets: { name: string; start?: string; offset?: number }[]) => Promise<unknown> }) {
  const [lines, setLines] = useState([{ name: '', start: '', offset: '' }])
  const [busy, setBusy] = useState(false)
  const ready = lines.some((l) => l.name.trim())
  const set = (i: number, k: 'name' | 'start' | 'offset', v: string) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l)))
  const submit = async () => {
    setBusy(true)
    try {
      await onCopy(lines.filter((l) => l.name.trim()).map((l) => ({ name: l.name.trim(), ...(l.start ? { start: l.start } : { offset: Number(l.offset) || 0 }) })))
      onClose()
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="lg" title="Copy to other units"
      description={source ? `Everything under ${source.wbs} ${source.name} is copied for each unit below, with the links among those rows. A unit starts on its own date, or is moved by a number of days.` : ''}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!ready} onClick={submit}>Copy</Button></>}>
      <div className="grid gap-2">
        {lines.map((l, i) => (
          <div key={i} className="grid grid-cols-[1fr_10rem_7rem_auto] items-end gap-2">
            <Field label={i === 0 ? 'Unit' : ''} htmlFor={`cu-n${i}`}><Input id={`cu-n${i}`} placeholder="A-18" value={l.name} onChange={(e) => set(i, 'name', e.target.value)} /></Field>
            <Field label={i === 0 ? 'Starts on' : ''} htmlFor={`cu-s${i}`}><Input id={`cu-s${i}`} type="date" value={l.start} onChange={(e) => set(i, 'start', e.target.value)} /></Field>
            <Field label={i === 0 ? 'or days later' : ''} htmlFor={`cu-o${i}`}><Input id={`cu-o${i}`} inputMode="numeric" placeholder="0" disabled={!!l.start} value={l.offset} onChange={(e) => set(i, 'offset', e.target.value)} /></Field>
            <Button variant="ghost" size="icon-sm" aria-label="Remove this unit" disabled={lines.length === 1} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}><Trash2 /></Button>
          </div>
        ))}
        <div><Button variant="outline" size="sm" onClick={() => setLines((ls) => [...ls, { name: '', start: '', offset: '' }])}><Plus /> Another unit</Button></div>
        <p className="text-xs text-muted-foreground">A link from inside the unit to a row outside it (A-18 waiting on A-16, say) is not copied: you are told which, to add again where it belongs.</p>
      </div>
    </Modal>
  )
}

/** The project's working week and holidays. */
export function CalendarModal({ open, view, editable, onClose, onSave, onAddHoliday, onRemoveHoliday, onPublic }: {
  open: boolean
  view: ProgrammeView
  editable: boolean
  onClose: () => void
  onSave: (calendarDays: boolean, weeklyOff: number[]) => Promise<unknown>
  onAddHoliday: (date: string, name: string) => Promise<unknown>
  onRemoveHoliday: (h: Holiday) => Promise<unknown>
  onPublic: (year: number) => Promise<unknown>
}) {
  const [calendarDays, setCalendarDays] = useState(view.calendar.calendar_days)
  const [off, setOff] = useState<number[]>(view.calendar.weekly_off)
  const [date, setDate] = useState('')
  const [name, setName] = useState('')
  const year = Number(today().slice(0, 4))
  const [pubYear, setPubYear] = useState(String(year))
  const changed = calendarDays !== view.calendar.calendar_days || off.join() !== view.calendar.weekly_off.join()
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="lg" title="Working days and holidays"
      description="Days are working days: a day off or a holiday is skipped when the End is worked out from the Days.">
      <div className="grid gap-5">
        <div>
          <p className="mb-2 text-sm font-medium">Days off each week</p>
          <div className="flex flex-wrap gap-2">
            {WEEKDAYS.map(([n, label]) => (
              <label key={n} className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-sm">
                <input type="checkbox" className="size-4 accent-primary" disabled={!editable || calendarDays} checked={off.includes(n)} onChange={(e) => setOff((o) => (e.target.checked ? [...o, n].sort() : o.filter((x) => x !== n)))} />{label}
              </label>
            ))}
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-primary" disabled={!editable} checked={calendarDays} onChange={(e) => setCalendarDays(e.target.checked)} />
            Count calendar days (every day counts; days off and holidays are not skipped)
          </label>
          {editable && <Button className="mt-3" size="sm" disabled={!changed} onClick={() => void onSave(calendarDays, off)}>Save working week</Button>}
        </div>
        <div>
          <p className="mb-2 text-sm font-medium">Holidays on this project</p>
          {view.calendar.holidays.length === 0 ? <p className="text-sm text-muted-foreground">None yet.</p> : (
            <ul className="grid max-h-56 gap-1 overflow-auto pr-1">
              {view.calendar.holidays.map((h) => (
                <li key={h.id} className="flex items-center gap-3 rounded-md border border-border px-3 py-1.5 text-sm">
                  <span className="w-28 tabular-nums">{formatDate(h.date)}</span><span className="min-w-0 flex-1 truncate">{h.name || '-'}</span>
                  {editable && <Button variant="ghost" size="icon-sm" aria-label={`Remove ${h.name || h.date}`} onClick={() => void onRemoveHoliday(h)}><Trash2 /></Button>}
                </li>
              ))}
            </ul>
          )}
          {editable && (
            <div className="mt-3 grid gap-3">
              <div className="grid grid-cols-[10rem_1fr_auto] items-end gap-2">
                <Field label="Date" htmlFor="hol-d"><Input id="hol-d" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
                <Field label="Holiday" htmlFor="hol-n"><Input id="hol-n" placeholder="Site closed" value={name} onChange={(e) => setName(e.target.value)} /></Field>
                <Button variant="outline" disabled={!date} onClick={() => { void onAddHoliday(date, name); setDate(''); setName('') }}><Plus /> Add</Button>
              </div>
              <div className="flex items-end gap-2">
                <Field label="India's public holidays for" htmlFor="hol-y"><Select id="hol-y" value={pubYear} onChange={(e) => setPubYear(e.target.value)} options={[year - 1, year, year + 1, year + 2].map((y) => ({ value: String(y), label: String(y) }))} /></Field>
                <Button variant="outline" onClick={() => void onPublic(Number(pubYear))}>Add them</Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </Modal>
  )
}

/** Everything about one row, including what the grid has no column for. */
export function RowDetailModal({ row, editable, onClose, onSave }: { row: ProgrammeRowView; editable: boolean; onClose: () => void; onSave: (change: RowChange) => Promise<unknown> }) {
  const [f, setF] = useState<Record<string, string | boolean>>(() => ({
    name: row.name, boq_ref: row.boq_ref, description: row.description, uom: row.uom, quantity: row.quantity ? String(row.quantity) : '',
    rate: row.rate ? String(row.rate) : '', amount: row.amount ? String(row.amount) : '', labour_required: row.labour_required ? String(row.labour_required) : '',
    not_before: row.not_before, milestone: row.milestone, productivity: row.productivity, output_per_day: row.output_per_day ? String(row.output_per_day) : '',
    gangs: row.gangs ? String(row.gangs) : '', predecessors: row.predecessors,
  }))
  const [busy, setBusy] = useState(false)
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF((x) => ({ ...x, [k]: e.target.type === 'checkbox' ? (e.target as HTMLInputElement).checked : e.target.value }))
  const save = async () => {
    const change: RowChange = { id: row.id }
    const original: Record<string, unknown> = { ...row }
    for (const [k, v] of Object.entries(f)) {
      if (row.summary && (k === 'predecessors' || k === 'not_before' || k === 'milestone' || k === 'productivity')) continue
      const before = original[k]
      const same = typeof v === 'boolean' ? v === before : String(v) === String(before ?? '') || (v === '' && !before)
      if (!same) (change as Record<string, unknown>)[k] = v
    }
    if (Object.keys(change).length === 1) return onClose()
    setBusy(true)
    try {
      await onSave(change)
      onClose()
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={`${row.wbs} ${row.name}`}
      description={row.summary ? 'A heading: its dates are those of the rows under it.' : `${row.start ? `${formatDate(row.start)} to ${formatDate(row.end!)}, ${row.days} working days` : 'Not scheduled yet'}${row.critical ? ' - on the critical path' : row.float_days ? ` - ${row.float_days} working days to spare` : ''}`}
      footer={editable ? <><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={save}>Save</Button></> : <Button variant="ghost" onClick={onClose}>Close</Button>}>
      <fieldset disabled={!editable} className="grid gap-3 sm:grid-cols-2">
        <Field label="Activity (short name)" htmlFor="rd-name" className="sm:col-span-2"><Input id="rd-name" value={String(f.name ?? '')} onChange={set('name')} /></Field>
        <Field label="Full description" htmlFor="rd-desc" className="sm:col-span-2">
          <textarea id="rd-desc" rows={4} value={String(f.description ?? '')} onChange={set('description')} className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm" />
        </Field>
        <Field label="BOQ Ref (V.NO)" htmlFor="rd-ref"><Input id="rd-ref" value={String(f.boq_ref ?? '')} onChange={set('boq_ref')} /></Field>
        <Field label="U.O.M" htmlFor="rd-uom"><Input id="rd-uom" value={String(f.uom ?? '')} onChange={set('uom')} /></Field>
        <Field label="Quantity" htmlFor="rd-qty"><Input id="rd-qty" inputMode="decimal" value={String(f.quantity ?? '')} onChange={set('quantity')} /></Field>
        <Field label="Labour required" htmlFor="rd-lab"><Input id="rd-lab" inputMode="decimal" value={String(f.labour_required ?? '')} onChange={set('labour_required')} /></Field>
        <Field label="Rate" htmlFor="rd-rate"><Input id="rd-rate" inputMode="decimal" value={String(f.rate ?? '')} onChange={set('rate')} /></Field>
        <Field label="Amount" htmlFor="rd-amt" hint="Weights this row's progress"><Input id="rd-amt" inputMode="decimal" value={String(f.amount ?? '')} onChange={set('amount')} /></Field>
        {!row.summary && <>
          <Field label="Predecessors" htmlFor="rd-pred" hint="1.1.2FS+1, 1.1.3SS+2 (FS, SS, FF or SF; + lag, - lead in working days)" className="sm:col-span-2"><Input id="rd-pred" value={String(f.predecessors ?? '')} onChange={set('predecessors')} /></Field>
          <Field label="Not earlier than" htmlFor="rd-nb"><Input id="rd-nb" type="date" value={String(f.not_before ?? '')} onChange={set('not_before')} /></Field>
          <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" className="size-4 accent-primary" checked={!!f.milestone} onChange={set('milestone')} />A milestone (takes no days)</label>
          <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" className="size-4 accent-primary" checked={!!f.productivity} onChange={set('productivity')} />Work out the days from the quantity: Days = Quantity ÷ (output per gang per day × gangs), rounded up</label>
          {!!f.productivity && <>
            <Field label="Output per gang per day" htmlFor="rd-out"><Input id="rd-out" inputMode="decimal" value={String(f.output_per_day ?? '')} onChange={set('output_per_day')} /></Field>
            <Field label="Gangs" htmlFor="rd-gangs"><Input id="rd-gangs" inputMode="decimal" value={String(f.gangs ?? '')} onChange={set('gangs')} /></Field>
          </>}
        </>}
      </fieldset>
      {row.baseline?.start && (
        <p className="mt-3 text-sm text-muted-foreground">Baseline: {formatDate(row.baseline.start)} to {formatDate(row.baseline.end!)}{row.baseline.slip_days ? ` - ${row.baseline.slip_days > 0 ? `${row.baseline.slip_days} days late` : `${-row.baseline.slip_days} days early`}` : ''}</p>
      )}
    </Modal>
  )
}

/** Save a baseline: the dates as they stand, kept to measure against. */
export function BaselineModal({ hasOne, onClose, onSave }: { hasOne: boolean; onClose: () => void; onSave: (label: string) => Promise<unknown> }) {
  const [label, setLabel] = useState(hasOne ? '' : 'Baseline 1')
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    try {
      if (await onSave(label.trim())) onClose()
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Save baseline"
      description={`Every row's Start, End and Days as they are now are kept. Planned % is then measured against them, and each row shows how far it has slipped.${hasOne ? ' The baseline saved before stays on record; this one is used from now on.' : ''}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={save}>Save baseline</Button></>}>
      <Field label="Call it" htmlFor="bl-label"><Input id="bl-label" placeholder="As agreed with the client, 2 Nov" value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
    </Modal>
  )
}
