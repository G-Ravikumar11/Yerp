import { useState } from 'react'
import { Field, Input, Modal, NumField, Select } from '@/components/ui'
import { eqKeys, serviceMachine, type Machine } from '@/api/equipment'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { Footer } from './Footer'

/** A service or repair, and whether the machine goes out of service for it. */
export function ServiceModal({ machine, onClose }: { machine: Machine | null; onClose: () => void }) {
  return (
    <Modal open={!!machine} onOpenChange={(o) => !o && onClose()} title={machine ? `Service ${machine.code} ${machine.name}` : ''} size="lg">
      {machine && <ServiceForm key={machine.id} machine={machine} onClose={onClose} />}
    </Modal>
  )
}

function ServiceForm({ machine, onClose }: { machine: Machine; onClose: () => void }) {
  const [date, setDate] = useState(today())
  const [kind, setKind] = useState(machine.service.due ? 'Preventive' : 'Repair')
  const [desc, setDesc] = useState('')
  const [vendor, setVendor] = useState('')
  const [n, setN] = useState({ parts: 0, labour: 0, down: 0 })
  const [meter, setMeter] = useState<number | null>(null)
  const [off, setOff] = useState(false)
  const num = (k: keyof typeof n) => (v: number) => setN((x) => ({ ...x, [k]: v }))
  const save = useAction(() => serviceMachine(machine.id, { service_on: date, kind, description: desc, vendor, parts_cost: n.parts, labour_cost: n.labour, downtime_hours: n.down, meter_at_service: meter, out_of_service: off }), { invalidate: [eqKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="On" htmlFor="sv-date"><Input id="sv-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Kind" htmlFor="sv-kind"><Select id="sv-kind" value={kind} onChange={(e) => setKind(e.target.value)} options={['Preventive', 'Repair', 'Breakdown', 'Inspection'].map((k) => ({ value: k, label: k }))} /></Field>
        <Field label={`Meter (now ${machine.meter_reading})`} htmlFor="sv-meter"><NumField id="sv-meter" value={meter ?? 0} onValue={setMeter} /></Field>
        <Field label="What was done" htmlFor="sv-desc" className="sm:col-span-2"><Input id="sv-desc" value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
        <Field label="By" htmlFor="sv-vendor"><Input id="sv-vendor" value={vendor} onChange={(e) => setVendor(e.target.value)} /></Field>
        <Field label="Parts" htmlFor="sv-parts"><NumField id="sv-parts" value={n.parts} onValue={num('parts')} /></Field>
        <Field label="Labour" htmlFor="sv-labour"><NumField id="sv-labour" value={n.labour} onValue={num('labour')} /></Field>
        <Field label="Down (hours)" htmlFor="sv-down"><NumField id="sv-down" value={n.down} onValue={num('down')} /></Field>
        <label className="flex items-center gap-2 text-sm sm:col-span-3"><input type="checkbox" checked={off} onChange={(e) => setOff(e.target.checked)} /> It stays out of service until it is back at work</label>
      </div>
      <Footer error={save.error?.message} busy={save.isPending} label="Record it" onClose={onClose} onSave={() => save.mutate()} />
    </div>
  )
}
