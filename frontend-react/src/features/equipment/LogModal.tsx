import { useState } from 'react'
import { Field, Input, Modal, NumField } from '@/components/ui'
import { eqKeys, logDay, type Machine } from '@/api/equipment'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { Footer } from './Footer'

const remembered = () => { try { return Number(localStorage.getItem('eqp-fuel-rate') || 0) } catch { return 0 } }

/** What the machine did today: hours, diesel, the meter. The cost lands on the site it worked for. */
export function LogModal({ machine, onClose }: { machine: Machine | null; onClose: () => void }) {
  const terms = machine ? (machine.ownership === 'Hired' ? `Hire is charged on its terms: ${formatINR(machine.hire_rate)} per ${machine.hire_basis.toLowerCase()}${machine.hire_basis === 'Month' ? ', spread over 26 working days' : ''}.` : 'An owned machine costs the site its diesel and its repairs.') : undefined
  return (
    <Modal open={!!machine} onOpenChange={(o) => !o && onClose()} title={machine ? `${machine.code} ${machine.name} - ${machine.current_job}` : ''} description={terms} size="lg">
      {machine && <LogForm key={machine.id} machine={machine} onClose={onClose} />}
    </Modal>
  )
}

function LogForm({ machine, onClose }: { machine: Machine; onClose: () => void }) {
  const [date, setDate] = useState(today())
  const [v, setV] = useState({ hours: 0, idle: 0, litres: 0, rate: remembered() })
  const [meter, setMeter] = useState<number | null>(null)
  const [operator, setOperator] = useState('')
  const [work, setWork] = useState('')
  const num = (k: keyof typeof v) => (n: number) => setV((x) => ({ ...x, [k]: n }))
  const save = useAction(() => {
    try { if (v.rate) localStorage.setItem('eqp-fuel-rate', String(v.rate)) } catch { /* the rate just is not remembered */ }
    return logDay(machine.id, { log_date: date, hours_worked: v.hours, idle_hours: v.idle, fuel_litres: v.litres, fuel_rate: v.rate, meter_reading: meter, operator, work_done: work })
  }, { invalidate: [eqKeys.all], success: (r) => `${r.message} Cost ${formatINR(r.cost)}.`, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Day" htmlFor="lg-date"><Input id="lg-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Hours worked" htmlFor="lg-hours"><NumField id="lg-hours" value={v.hours} onValue={num('hours')} autoFocus /></Field>
        <Field label="Hours idle" htmlFor="lg-idle"><NumField id="lg-idle" value={v.idle} onValue={num('idle')} /></Field>
        <Field label="Diesel (litres)" htmlFor="lg-litres"><NumField id="lg-litres" value={v.litres} onValue={num('litres')} /></Field>
        <Field label="Diesel rate" htmlFor="lg-rate"><NumField id="lg-rate" value={v.rate} onValue={num('rate')} /></Field>
        <Field label={`Meter (now ${machine.meter_reading})`} htmlFor="lg-meter"><NumField id="lg-meter" value={meter ?? 0} onValue={setMeter} /></Field>
        <Field label="Operator" htmlFor="lg-op"><Input id="lg-op" value={operator} onChange={(e) => setOperator(e.target.value)} /></Field>
        <Field label="Work done" htmlFor="lg-work" className="sm:col-span-2"><Input id="lg-work" value={work} onChange={(e) => setWork(e.target.value)} /></Field>
      </div>
      <Footer error={save.error?.message} busy={save.isPending} label="Log the day" onClose={onClose} onSave={() => save.mutate()} />
    </div>
  )
}
