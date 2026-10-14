import { useState } from 'react'
import { CalendarClock } from 'lucide-react'
import { Button, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { eqKeys, saveMachine, type IntervalType, type LocationType, type Machine } from '@/api/equipment'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { ServiceBadge } from './plantParts'
import { INTERVAL_OPTIONS, UNIT_OPTIONS, previewSchedule, unitWord } from './schedule'

export function MachineModal({ machine, categories, open, onClose }: { machine: Machine | null; categories: string[]; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={machine ? `Edit ${machine.code}` : 'Add a machine'} description="What the business owns, and what it hires in." size="lg">
      {open && <Form key={machine?.id ?? 'new'} machine={machine} categories={categories} onClose={onClose} />}
    </Modal>
  )
}

/** A number that may be left blank - blank is "not known", never nought. */
function OptNum({ id, value, onChange, placeholder, disabled }: { id: string; value: string; onChange: (v: string) => void; placeholder?: string; disabled?: boolean }) {
  return <Input id={id} inputMode="decimal" className="tabular text-right" value={value} placeholder={placeholder} disabled={disabled} onChange={(e) => { if (e.target.value === '' || /^\d*\.?\d*$/.test(e.target.value)) onChange(e.target.value) }} />
}
const toNum = (s: string) => (s.trim() === '' || s === '.' ? null : Number(s))

function Form({ machine: a, categories, onClose }: { machine: Machine | null; categories: string[]; onClose: () => void }) {
  const [f, setF] = useState({
    name: a?.name ?? '', category: a?.category ?? 'Earthmoving', ownership: a?.ownership ?? 'Owned', brand: a?.brand ?? '', model: a?.model ?? '', reg_no: a?.reg_no ?? '',
    hired_from: a?.hired_from ?? '', hire_basis: a?.hire_basis ?? 'Day', meter_unit: a?.meter_unit ?? 'Hours', last_service_on: a?.last_service_on ?? '', purchase_date: a?.purchase_date ?? '',
    insurance_until: a?.insurance_until ?? '', fitness_until: a?.fitness_until ?? '', notes: a?.notes ?? '', code: a?.code ?? '', condition: a?.condition ?? 'Good',
  })
  const [n, setN] = useState({ hire_rate: a?.hire_rate ?? 0, meter_reading: a?.meter_reading ?? 0, service_every: a?.service_every ?? 0, service_every_days: a?.service_every_days ?? 0, purchase_value: a?.purchase_value ?? 0 })
  const [type, setType] = useState<IntervalType>(a?.service_interval_type ?? 'Both')
  const jobs = useProjects()
  // Never assumed: a new machine has to be said to be in the yard, on a site, or in transit.
  const [where, setWhere] = useState<{ kind: LocationType | ''; site: string }>({ kind: a?.location_type ?? '', site: a?.location_id ? String(a.location_id) : '' })
  const [opt, setOpt] = useState({
    lastMeter: a?.last_service_meter != null ? String(a.last_service_meter) : '',
    remMeter: a?.reminder_meter != null ? String(a.reminder_meter) : '',
    remDays: a?.reminder_days != null ? String(a.reminder_days) : '',
  })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const num = (k: keyof typeof n) => (v: number) => setN((x) => ({ ...x, [k]: v }))
  const setO = (k: keyof typeof opt) => (v: string) => setOpt((x) => ({ ...x, [k]: v }))
  const hired = f.ownership === 'Hired' || f.ownership === 'Leased'

  const unit = unitWord(f.meter_unit)
  // A new machine with the last-service reading left blank counts from the reading it comes in at - the server does the same.
  const lastMeter = toNum(opt.lastMeter) ?? (a ? null : n.meter_reading)
  const remMeter = toNum(opt.remMeter)
  const remDays = toNum(opt.remDays)
  const p = previewSchedule({ type, unit: f.meter_unit, meterNow: n.meter_reading, everyMeter: n.service_every, everyDays: n.service_every_days, lastMeter, lastOn: f.last_service_on, reminderMeter: remMeter, reminderDays: remDays })
  const errors = {
    where: where.kind === 'Site' && !where.site ? 'Choose the site.' : !a && where.kind === '' ? 'Say where the machine is.' : '',
    meter: n.meter_reading < 0 ? 'A meter reading cannot be negative.' : '',
    every: p.usesMeter && !(n.service_every > 0) ? `How many ${unit} between services?` : '',
    days: p.usesDays && !(n.service_every_days > 0) ? 'How many days between services?' : p.usesDays && !Number.isInteger(n.service_every_days) ? 'A whole number of days.' : '',
    lastMeter: !p.usesMeter ? '' : lastMeter === null ? 'The reading at the last service - the next one is counted from it.' : lastMeter > n.meter_reading ? `The meter reads ${n.meter_reading} now; it cannot have been serviced at ${lastMeter}.` : '',
    lastOn: !p.usesDays ? '' : !f.last_service_on ? 'The date of the last service, or the day it started work.' : f.last_service_on > today() ? 'That date has not come yet.' : f.last_service_on < '1980-01-01' ? 'Check the year.' : '',
    remMeter: p.usesMeter && remMeter !== null && n.service_every > 0 && remMeter >= n.service_every ? `Fewer than ${n.service_every} ${unit}.` : '',
    remDays: p.usesDays && remDays !== null && n.service_every_days > 0 && (!Number.isInteger(remDays) || remDays >= n.service_every_days) ? `A whole number of days, fewer than ${n.service_every_days}.` : '',
  }
  const invalid = Object.values(errors).some(Boolean)
  const save = useAction(() => saveMachine(a?.id ?? null, {
    ...f, ...n, service_interval_type: type,
    location_type: where.kind || undefined, location_id: where.kind === 'Site' ? Number(where.site) : undefined,
    service_every: p.usesMeter ? n.service_every : 0, service_every_days: p.usesDays ? n.service_every_days : 0,
    last_service_meter: toNum(opt.lastMeter), reminder_meter: p.usesMeter ? remMeter : null, reminder_days: p.usesDays ? remDays : null,
  }), { invalidate: [eqKeys.all], success: (r) => `${r.code} ${r.name} saved`, onSuccess: onClose })

  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Equipment ID" htmlFor="mc-code" hint={a ? undefined : 'Left blank, the next EQP number'}><Input id="mc-code" value={f.code} maxLength={30} onChange={set('code')} /></Field>
        <Field label="Machine" htmlFor="mc-name" className="sm:col-span-2"><Input id="mc-name" value={f.name} onChange={set('name')} autoFocus /></Field>
        <Field label="Category" htmlFor="mc-cat"><Select id="mc-cat" value={f.category} onChange={set('category')} options={(categories.length ? categories : ['Other']).map((c) => ({ value: c, label: c }))} /></Field>
        <Field label="Brand" htmlFor="mc-brand"><Input id="mc-brand" value={f.brand} placeholder="e.g. JCB" onChange={set('brand')} /></Field>
        <Field label="Model" htmlFor="mc-model"><Input id="mc-model" value={f.model} onChange={set('model')} /></Field>
        <Field label="Registration no." htmlFor="mc-reg"><Input id="mc-reg" value={f.reg_no} onChange={set('reg_no')} /></Field>
        <Field label="Ownership" htmlFor="mc-own"><Select id="mc-own" value={f.ownership} onChange={set('ownership')} options={[{ value: 'Owned', label: 'Owned' }, { value: 'Hired', label: 'Rented' }, { value: 'Leased', label: 'Leased' }]} /></Field>
        <Field label="Condition" htmlFor="mc-cond"><Select id="mc-cond" value={f.condition} onChange={set('condition')} options={['Good', 'Fair', 'Poor'].map((c) => ({ value: c, label: c }))} /></Field>
        <Field label="Where is it" htmlFor="mc-where" error={errors.where}><Select id="mc-where" value={where.kind} placeholder="Choose" onChange={(e) => setWhere({ kind: e.target.value as LocationType | '', site: '' })} options={[{ value: 'Yard', label: 'Yard' }, { value: 'Site', label: 'Site' }, { value: 'Transit', label: 'In transit' }]} /></Field>
        {where.kind === 'Site' && (
          <Field label="Site" htmlFor="mc-site" className="sm:col-span-2"><Select id="mc-site" value={where.site} placeholder={jobs.isPending ? 'Loading...' : 'Choose the site'} onChange={(e) => setWhere((w) => ({ ...w, site: e.target.value }))} options={(jobs.data ?? []).filter((j) => String(j.id) === where.site || !['complete', 'cancelled'].includes(j.status)).map((j) => ({ value: j.id, label: projectLabel(j) }))} /></Field>
        )}
      </div>
      {/* Hired machines have three of these and owned ones two, so each set has its own row and none is left half full. */}
      <div className={`mt-4 grid gap-4 ${hired ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}>
        {hired ? (
          <>
            <Field label={f.ownership === 'Leased' ? 'Leased from' : 'Rented from'} htmlFor="mc-from"><Input id="mc-from" value={f.hired_from} onChange={set('hired_from')} /></Field>
            <Field label={f.ownership === 'Leased' ? 'Lease rate' : 'Hire rate'} htmlFor="mc-rate"><NumField id="mc-rate" value={n.hire_rate} onValue={num('hire_rate')} /></Field>
            <Field label="Charged per" htmlFor="mc-basis"><Select id="mc-basis" value={f.hire_basis} onChange={set('hire_basis')} options={['Hour', 'Day', 'Month'].map((b) => ({ value: b, label: b }))} /></Field>
          </>
        ) : (
          <>
            <Field label="Bought on" htmlFor="mc-bought"><Input id="mc-bought" type="date" value={f.purchase_date} onChange={set('purchase_date')} /></Field>
            <Field label="Cost" htmlFor="mc-value"><NumField id="mc-value" value={n.purchase_value} onValue={num('purchase_value')} /></Field>
          </>
        )}
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="Insurance until" htmlFor="mc-ins"><Input id="mc-ins" type="date" value={f.insurance_until} onChange={set('insurance_until')} /></Field>
        <Field label="Fitness until" htmlFor="mc-fit"><Input id="mc-fit" type="date" value={f.fitness_until} onChange={set('fitness_until')} /></Field>
      </div>

      <fieldset aria-label="Maintenance schedule" className="mt-5 rounded-xl border border-border p-4">
        <legend className="px-1.5 text-sm font-semibold">Maintenance schedule</legend>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Service interval type" htmlFor="mc-itype" className="sm:col-span-3"><Select id="mc-itype" value={type} onChange={(e) => setType(e.target.value as IntervalType)} options={INTERVAL_OPTIONS} /></Field>
          <Field label="Meter measures" htmlFor="mc-unit"><Select id="mc-unit" value={f.meter_unit} onChange={set('meter_unit')} options={UNIT_OPTIONS} /></Field>
          <Field label={`Meter reading now (${unit})`} htmlFor="mc-meter" error={errors.meter} hint={a ? 'Moves as days are logged' : undefined}><NumField id="mc-meter" value={n.meter_reading} onValue={num('meter_reading')} disabled={!!a} /></Field>
          <div className="hidden sm:block" />
          {p.usesMeter && (
            <>
              <Field label={`Service every (${unit})`} htmlFor="mc-every" error={errors.every}><NumField id="mc-every" value={n.service_every} onValue={num('service_every')} /></Field>
              <Field label={`Meter at last service (${unit})`} htmlFor="mc-lastmeter" error={errors.lastMeter} hint={!a && opt.lastMeter === '' ? `Blank: today's reading (${n.meter_reading})` : undefined}><OptNum id="mc-lastmeter" value={opt.lastMeter} onChange={setO('lastMeter')} /></Field>
              <Field label={`Remind early by (${unit})`} htmlFor="mc-remmeter" error={errors.remMeter} hint={opt.remMeter === '' ? `Blank: a tenth of the interval${n.service_every > 0 ? ` (${p.remM})` : ''}` : undefined}><OptNum id="mc-remmeter" value={opt.remMeter} onChange={setO('remMeter')} /></Field>
            </>
          )}
          {p.usesDays && (
            <>
              <Field label="Service every (days)" htmlFor="mc-days" error={errors.days}><NumField id="mc-days" value={n.service_every_days} onValue={num('service_every_days')} /></Field>
              <Field label="Last serviced on" htmlFor="mc-lastsvc" error={errors.lastOn}><Input id="mc-lastsvc" type="date" min="1980-01-01" max={today()} value={f.last_service_on} onChange={set('last_service_on')} /></Field>
              <Field label="Remind early by (days)" htmlFor="mc-remdays" error={errors.remDays} hint={opt.remDays === '' ? `Blank: a tenth of the interval, at least 3${n.service_every_days > 0 ? ` (${p.remD})` : ''}` : undefined}><OptNum id="mc-remdays" value={opt.remDays} onChange={setO('remDays')} /></Field>
            </>
          )}
        </div>
        <div aria-live="polite" aria-label="Schedule summary" className="mt-4 flex gap-3 rounded-lg border border-border bg-surface p-3 text-[13px]">
          <CalendarClock className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="mb-1"><ServiceBadge status={p.status} /></div>
            {p.lines.map((l) => <p key={l}>{l}</p>)}
          </div>
        </div>
      </fieldset>

      <Field label="Notes" htmlFor="mc-notes" className="mt-4"><Textarea id="mc-notes" rows={2} value={f.notes} onChange={set('notes')} /></Field>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!f.name.trim() || invalid} onClick={() => save.mutate()}>Save the machine</Button>
      </div>
    </div>
  )
}
