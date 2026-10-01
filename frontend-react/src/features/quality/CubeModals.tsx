import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select, Textarea } from '@/components/ui'
import { cubeResult, logCubes, qcKeys, raiseNcr, type CubeSet } from '@/api/quality'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'

export function CubeSetModal({ job, open, onClose }: { job: number; open: boolean; onClose: () => void }) {
  const [f, setF] = useState({ cast_on: today(), grade: 'M25', location: '', supplier: '', docket: '' })
  const [slump, setSlump] = useState(0)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const save = useAction(() => logCubes({ job_id: job, ...f, slump_mm: slump }), { invalidate: [qcKeys.all], success: (r) => `${r.cube_set.number} logged. Its 7- and 28-day tests are now tracked.`, onSuccess: onClose })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Cubes cast" description="Log each pour's cubes the day they are cast.">
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Cast on" htmlFor="cs-date"><Input id="cs-date" type="date" value={f.cast_on} onChange={set('cast_on')} /></Field>
        <Field label="Grade" htmlFor="cs-grade"><Input id="cs-grade" value={f.grade} onChange={set('grade')} /></Field>
        <Field label="Slump (mm)" htmlFor="cs-slump"><NumField id="cs-slump" value={slump} onValue={setSlump} /></Field>
        <Field label="Which pour" htmlFor="cs-where" className="sm:col-span-3"><Input id="cs-where" value={f.location} placeholder="Raft pour 1, grid A-C" onChange={set('location')} /></Field>
        <Field label="RMC plant / mixer" htmlFor="cs-sup" className="sm:col-span-2"><Input id="cs-sup" value={f.supplier} onChange={set('supplier')} /></Field>
        <Field label="Docket no." htmlFor="cs-dock"><Input id="cs-dock" value={f.docket} onChange={set('docket')} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => save.mutate()}>Log the set</Button>
      </div>
    </Modal>
  )
}

/** A crushing result: the age at test and the strength of each cube. */
export function CubeResultModal({ set, onClose }: { set: CubeSet | null; onClose: () => void }) {
  return (
    <Modal open={!!set} onOpenChange={(o) => !o && onClose()} title={set ? `${set.number} ${set.grade} - crushing result` : 'Result'} description="Strengths in N/mm2, one per cube. Seven-day results are expected near two-thirds of the grade; twenty-eight-day results are read against it.">
      {set && <ResultForm key={set.id} set={set} onClose={onClose} />}
    </Modal>
  )
}

function ResultForm({ set, onClose }: { set: CubeSet; onClose: () => void }) {
  const [age, setAge] = useState(String(set.due[0]?.age_days ?? 28))
  const [strengths, setStrengths] = useState('')
  const save = useAction(() => cubeResult(set.id, parseInt(age), strengths), {
    invalidate: [qcKeys.all],
    success: (r) => { const x = r.cube_set.results.find((y) => y.age_days === parseInt(age)); return `${r.cube_set.number} at ${age} days: ${x?.average} N/mm2 - ${x?.verdict}` },
    onSuccess: onClose,
  })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Age at test (days)" htmlFor="cr-age"><Select id="cr-age" value={age} onChange={(e) => setAge(e.target.value)} options={[{ value: '3', label: '3' }, { value: '7', label: '7' }, { value: '14', label: '14' }, { value: '28', label: '28' }]} /></Field>
        <Field label="Strength of each cube" htmlFor="cr-str" hint="Separated by commas, e.g. 24.5, 25.1, 26" className="sm:col-span-2"><Textarea id="cr-str" rows={2} value={strengths} onChange={(e) => setStrengths(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!strengths.trim()} onClick={() => save.mutate()}>Record it</Button>
      </div>
    </div>
  )
}

/** Raise a non-conformance: from a failed inspection or a cube set below grade, or freestanding. */
export function NcrModal({ job, from, open, onClose, onRaised }: { job: number; from: { type: string; id: number } | null; open: boolean; onClose: () => void; onRaised: () => void }) {
  const [what, setWhat] = useState('')
  const [where, setWhere] = useState('')
  const [who, setWho] = useState('')
  const [by, setBy] = useState('')
  const [major, setMajor] = useState('Minor')
  const save = useAction(() => raiseNcr(from ? { source_type: from.type, source_id: from.id, responsible: who, target_date: by, severity: major } : { job_id: job, description: what, location: where, responsible: who, target_date: by, severity: major }), { invalidate: [qcKeys.all], success: (r) => `${r.ncr.number} raised`, onSuccess: () => { onRaised(); onClose() } })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Raise a non-conformance" description={from ? 'Filled in from what failed.' : 'Anything not as specified stays open until it is put right.'}>
      <div className="grid gap-4 sm:grid-cols-2">
        {!from && <Field label="What is not as specified" htmlFor="nc-what" className="sm:col-span-2"><Textarea id="nc-what" rows={2} value={what} onChange={(e) => setWhat(e.target.value)} /></Field>}
        {!from && <Field label="Where" htmlFor="nc-where"><Input id="nc-where" value={where} onChange={(e) => setWhere(e.target.value)} /></Field>}
        <Field label="Who puts it right" htmlFor="nc-who"><Input id="nc-who" value={who} placeholder="The gang, the supplier..." onChange={(e) => setWho(e.target.value)} /></Field>
        <Field label="By when" htmlFor="nc-by"><Input id="nc-by" type="date" value={by} onChange={(e) => setBy(e.target.value)} /></Field>
        <Field label="How serious" htmlFor="nc-major"><Select id="nc-major" value={major} onChange={(e) => setMajor(e.target.value)} options={[{ value: 'Minor', label: 'Minor' }, { value: 'Major', label: 'Major' }]} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!from && !what.trim()} onClick={() => save.mutate()}>Raise it</Button>
      </div>
    </Modal>
  )
}
