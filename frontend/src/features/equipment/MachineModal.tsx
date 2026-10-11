import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { eqKeys, saveMachine, type Machine } from '@/api/equipment'
import { useAction } from '@/lib/mutate'

export function MachineModal({ machine, categories, open, onClose }: { machine: Machine | null; categories: string[]; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={machine ? `Edit ${machine.code}` : 'Add a machine'} description="What the business owns, and what it hires in." size="lg">
      {open && <Form key={machine?.id ?? 'new'} machine={machine} categories={categories} onClose={onClose} />}
    </Modal>
  )
}

function Form({ machine: a, categories, onClose }: { machine: Machine | null; categories: string[]; onClose: () => void }) {
  const [f, setF] = useState({
    name: a?.name ?? '', category: a?.category ?? 'Earthmoving', ownership: a?.ownership ?? 'Owned', make: a?.make ?? '', model: a?.model ?? '', reg_no: a?.reg_no ?? '', serial_no: a?.serial_no ?? '',
    hired_from: a?.hired_from ?? '', hire_basis: a?.hire_basis ?? 'Day', meter_unit: a?.meter_unit ?? 'Hours', last_service_on: a?.last_service_on ?? '', purchase_date: a?.purchase_date ?? '',
    insurance_until: a?.insurance_until ?? '', fitness_until: a?.fitness_until ?? '', notes: a?.notes ?? '',
  })
  const [n, setN] = useState({ hire_rate: a?.hire_rate ?? 0, meter_reading: a?.meter_reading ?? 0, service_every: a?.service_every ?? 0, service_every_days: a?.service_every_days ?? 0, purchase_value: a?.purchase_value ?? 0 })
  const [lastMeter, setLastMeter] = useState<number | null>(a ? (a.last_service_meter ?? 0) : null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const num = (k: keyof typeof n) => (v: number) => setN((x) => ({ ...x, [k]: v }))
  const hired = f.ownership === 'Hired'
  const save = useAction(() => saveMachine(a?.id ?? null, { ...f, ...n, last_service_meter: lastMeter }), { invalidate: [eqKeys.all], success: (r) => `${r.code} ${r.name} saved`, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Machine" htmlFor="mc-name" className="sm:col-span-2"><Input id="mc-name" value={f.name} onChange={set('name')} autoFocus /></Field>
        <Field label="Category" htmlFor="mc-cat"><Select id="mc-cat" value={f.category} onChange={set('category')} options={(categories.length ? categories : ['Other']).map((c) => ({ value: c, label: c }))} /></Field>
        <Field label="Make" htmlFor="mc-make"><Input id="mc-make" value={f.make} onChange={set('make')} /></Field>
        <Field label="Model" htmlFor="mc-model"><Input id="mc-model" value={f.model} onChange={set('model')} /></Field>
        <Field label="Registration no." htmlFor="mc-reg"><Input id="mc-reg" value={f.reg_no} onChange={set('reg_no')} /></Field>
        <Field label="Serial no." htmlFor="mc-serial"><Input id="mc-serial" value={f.serial_no} onChange={set('serial_no')} /></Field>
        <Field label="Owned or hired" htmlFor="mc-own"><Select id="mc-own" value={f.ownership} onChange={set('ownership')} options={[{ value: 'Owned', label: 'Owned' }, { value: 'Hired', label: 'Hired in' }]} /></Field>
        {hired ? (
          <>
            <Field label="Hired from" htmlFor="mc-from"><Input id="mc-from" value={f.hired_from} onChange={set('hired_from')} /></Field>
            <Field label="Hire rate" htmlFor="mc-rate"><NumField id="mc-rate" value={n.hire_rate} onValue={num('hire_rate')} /></Field>
            <Field label="Charged per" htmlFor="mc-basis"><Select id="mc-basis" value={f.hire_basis} onChange={set('hire_basis')} options={['Hour', 'Day', 'Month'].map((b) => ({ value: b, label: b }))} /></Field>
          </>
        ) : (
          <>
            <Field label="Bought on" htmlFor="mc-bought"><Input id="mc-bought" type="date" value={f.purchase_date} onChange={set('purchase_date')} /></Field>
            <Field label="Cost" htmlFor="mc-value"><NumField id="mc-value" value={n.purchase_value} onValue={num('purchase_value')} /></Field>
          </>
        )}
        <Field label="Meter counts in" htmlFor="mc-unit"><Select id="mc-unit" value={f.meter_unit} onChange={set('meter_unit')} options={['Hours', 'Km'].map((u) => ({ value: u, label: u }))} /></Field>
        <Field label="Meter reading now" htmlFor="mc-meter" hint={a ? 'Changes as days are logged' : undefined}><NumField id="mc-meter" value={n.meter_reading} onValue={num('meter_reading')} disabled={!!a} /></Field>
        <Field label="Service every (meter)" htmlFor="mc-every"><NumField id="mc-every" value={n.service_every} onValue={num('service_every')} /></Field>
        <Field label="Or every (days)" htmlFor="mc-days"><NumField id="mc-days" value={n.service_every_days} onValue={num('service_every_days')} /></Field>
        <Field label="Last serviced on" htmlFor="mc-lastsvc"><Input id="mc-lastsvc" type="date" value={f.last_service_on} onChange={set('last_service_on')} /></Field>
        <Field label="Meter at last service" htmlFor="mc-lastmeter" hint="Blank counts from today's reading"><NumField id="mc-lastmeter" value={lastMeter ?? 0} onValue={setLastMeter} /></Field>
        <Field label="Insurance until" htmlFor="mc-ins"><Input id="mc-ins" type="date" value={f.insurance_until} onChange={set('insurance_until')} /></Field>
        <Field label="Fitness until" htmlFor="mc-fit"><Input id="mc-fit" type="date" value={f.fitness_until} onChange={set('fitness_until')} /></Field>
        <Field label="Notes" htmlFor="mc-notes" className="sm:col-span-3"><Textarea id="mc-notes" rows={2} value={f.notes} onChange={set('notes')} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!f.name.trim()} onClick={() => save.mutate()}>Save the machine</Button>
      </div>
    </div>
  )
}
