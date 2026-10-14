import { useState } from 'react'
import { Field, Input, Modal, NumField, Textarea } from '@/components/ui'
import { completeService, eqKeys, type Machine } from '@/api/equipment'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'
import { FormFoot, ServiceBadge } from './plantParts'
import { previewSchedule, unitWord } from './schedule'

/** The scheduled service, done: into the history, and the clock starts again from it. */
export function ServiceDoneModal({ machine, onClose }: { machine: Machine | null; onClose: () => void }) {
  return (
    <Modal open={!!machine} onOpenChange={(o) => !o && onClose()} title={machine ? `Service done - ${machine.code} ${machine.name}` : ''} description="Records the service and works out when the next one is due." size="lg">
      {machine && <DoneForm key={machine.id} machine={machine} onClose={onClose} />}
    </Modal>
  )
}

const opt = (s: string) => (s.trim() === '' ? null : Number(s))

function DoneForm({ machine: m, onClose }: { machine: Machine; onClose: () => void }) {
  const sch = m.service.schedule
  const unit = unitWord(m.meter_unit)
  const [f, setF] = useState({ completed_on: today(), work_performed: '', parts_used: '', vendor: '', invoice_no: '', next_service_on: '' })
  const [meter, setMeter] = useState(String(m.meter_reading))
  const [nextMeter, setNextMeter] = useState('')
  const [cost, setCost] = useState({ parts: 0, labour: 0 })
  const [tried, setTried] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const reading = opt(meter)
  const usesMeter = sch.type === 'Both' || sch.type === 'Meter'
  const usesDays = sch.type === 'Both' || sch.type === 'Days'
  // What the next thresholds come to: the interval on from this service, unless given here.
  const p = previewSchedule({ type: sch.type, unit: m.meter_unit, meterNow: Math.max(reading ?? 0, m.meter_reading), everyMeter: sch.every_meter, everyDays: sch.every_days,
    lastMeter: reading, lastOn: f.completed_on, reminderMeter: m.reminder_meter, reminderDays: m.reminder_days })
  const nm = opt(nextMeter) ?? p.nextMeter
  const nd = f.next_service_on || p.nextOn
  const errors = {
    on: !f.completed_on ? 'When was it done?' : f.completed_on > today() ? 'That date has not come yet.' : f.completed_on < '1980-01-01' ? 'Check the year.' : sch.last_service_on && f.completed_on < sch.last_service_on ? `It was last serviced on ${formatDate(sch.last_service_on)}.` : '',
    work: f.work_performed.trim() ? '' : 'Say what was done.',
    meter: usesMeter && reading === null ? 'The reading at this service - the next one is counted from it.' : reading !== null && sch.last_service_meter !== null && reading < sch.last_service_meter ? `It was last serviced at ${sch.last_service_meter} ${unit}.` : '',
    nextMeter: opt(nextMeter) !== null && (reading === null || opt(nextMeter)! <= reading) ? 'Above this reading.' : '',
    nextOn: f.next_service_on && f.next_service_on <= f.completed_on ? 'After this service.' : '',
  }
  const first = Object.values(errors).find(Boolean)
  // Shown once a save is tried - not before anything has been typed.
  const show = tried ? errors : ({} as Partial<typeof errors>)
  const save = useAction(() => completeService(m.id, { ...f, meter_at_service: reading, next_service_meter: opt(nextMeter), parts_cost: cost.parts, labour_cost: cost.labour }), { invalidate: [eqKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <div>
      <p className="mb-4 flex flex-wrap items-center gap-2 text-[13px]"><ServiceBadge status={sch.status} />{sch.reasons.join('; ') || 'On schedule.'}</p>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Serviced on" htmlFor="sd-on" error={show.on}><Input id="sd-on" type="date" max={today()} value={f.completed_on} onChange={set('completed_on')} /></Field>
        <Field label={`Meter at service (${unit})`} htmlFor="sd-meter" error={show.meter} hint={usesMeter ? undefined : 'Optional for a calendar schedule'}><Input id="sd-meter" inputMode="decimal" className="tabular text-right" value={meter} onChange={(e) => { if (/^\d*\.?\d*$/.test(e.target.value)) setMeter(e.target.value) }} /></Field>
        <Field label="Done by" htmlFor="sd-by"><Input id="sd-by" value={f.vendor} onChange={set('vendor')} placeholder="Mechanic or workshop" /></Field>
        <Field label="Work performed" htmlFor="sd-work" error={show.work} className="sm:col-span-3"><Textarea id="sd-work" rows={2} value={f.work_performed} onChange={set('work_performed')} /></Field>
        <Field label="Parts used" htmlFor="sd-parts" className="sm:col-span-3"><Input id="sd-parts" value={f.parts_used} onChange={set('parts_used')} placeholder="Oil, filters, grease..." /></Field>
        <Field label="Parts cost" htmlFor="sd-pc"><NumField id="sd-pc" value={cost.parts} onValue={(v) => setCost((x) => ({ ...x, parts: v }))} /></Field>
        <Field label="Labour cost" htmlFor="sd-lc"><NumField id="sd-lc" value={cost.labour} onValue={(v) => setCost((x) => ({ ...x, labour: v }))} /></Field>
        <Field label="Invoice no." htmlFor="sd-inv"><Input id="sd-inv" value={f.invoice_no} onChange={set('invoice_no')} /></Field>
        {usesMeter && <Field label={`Next service at (${unit})`} htmlFor="sd-nm" error={show.nextMeter} hint={p.nextMeter !== null && !nextMeter ? `Blank: ${p.nextMeter}` : undefined}><Input id="sd-nm" inputMode="decimal" className="tabular text-right" value={nextMeter} onChange={(e) => { if (/^\d*\.?\d*$/.test(e.target.value)) setNextMeter(e.target.value) }} /></Field>}
        {usesDays && <Field label="Next service on" htmlFor="sd-nd" error={show.nextOn} hint={p.nextOn && !f.next_service_on ? `Blank: ${formatDate(p.nextOn)}` : undefined}><Input id="sd-nd" type="date" value={f.next_service_on} onChange={set('next_service_on')} /></Field>}
      </div>
      <p aria-live="polite" className="mt-4 rounded-lg border border-border bg-surface p-3 text-[13px]">
        Next service due {[nm !== null && usesMeter ? `at ${nm.toLocaleString('en-IN')} ${unit}` : '', nd && usesDays ? `on ${formatDate(nd)}` : ''].filter(Boolean).join(' or ') || 'once the reading is entered'}{nm !== null && nd && usesMeter && usesDays ? ', whichever comes first' : ''}.
      </p>
      <FormFoot error={save.error?.message ?? (tried ? first : undefined)} busy={save.isPending} label="Record the service" onClose={onClose} onSave={() => { setTried(true); if (!first) save.mutate() }} />
    </div>
  )
}
