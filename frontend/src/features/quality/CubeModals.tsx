import { useState } from 'react'
import { FileText } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select, Skeleton, Textarea } from '@/components/ui'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { cubeResult, decideCube, flagCube, logCubes, qcKeys, useCube, useCriteria, type CubeSet } from '@/api/quality'
import { uploadFiles } from '@/api/files'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { toast } from '@/stores/toast'
import { Fact, FilePick, History, Section, cubeTone } from './parts'

const blank = { grade: 'M25', location: '', pour_ref: '', cube_ids: '', supplier: '', docket: '', test_ages: '', remarks: '' }

/** Register the cubes cast from a pour. The ages to test at follow the project's criteria unless given here. */
export function CubeSetModal({ job, open, onClose, onLogged }: { job: number; open: boolean; onClose: () => void; onLogged: (c: CubeSet) => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Register concrete cubes" description="Log each pour's cubes the day they are cast." size="lg">
      {open && <SetForm job={job} onClose={onClose} onLogged={onLogged} />}
    </Modal>
  )
}

function SetForm({ job: initial, onClose, onLogged }: { job: number; onClose: () => void; onLogged: (c: CubeSet) => void }) {
  const [job, setJob] = useState(initial)
  const [f, setF] = useState(blank)
  const [cast, setCast] = useState(today())
  const [slump, setSlump] = useState(0)
  const [tried, setTried] = useState(false)
  const crit = useCriteria(job)
  const set = (k: keyof typeof blank) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const grade = f.grade.trim().toUpperCase()
  const ages = (crit.data ?? []).filter((c) => c.grade === grade).map((c) => c.age_days).sort((a, b) => a - b)
  const errors = {
    job: job ? '' : 'Choose the project.',
    grade: /^M\d{2,3}$/.test(grade) ? '' : 'The grade as it is written: M20, M25, M30...',
    cast: !cast ? 'Give the casting date.' : cast > today() ? 'Cubes cannot be cast in the future.' : '',
    ages: !f.test_ages.trim() || /^\s*\d+(\s*[, ]\s*\d+)*\s*$/.test(f.test_ages) ? '' : 'Ages in days, separated by commas: 7, 28.',
  }
  const bad = Object.values(errors).some(Boolean)
  const save = useAction(() => logCubes({ job_id: job, ...f, grade, cast_on: cast, slump_mm: slump }), { invalidate: [qcKeys.all], success: (r) => `${r.cube_set.number} registered. Tests are due at ${r.cube_set.test_ages.join(' and ')} days.`, onSuccess: (r) => onLogged(r.cube_set) })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Project" htmlFor="cs-job" error={tried ? errors.job : ''} className="sm:col-span-3"><ProjectPicker id="cs-job" value={job} onChange={setJob} className="w-full" /></Field>
        <Field label="Concrete grade" htmlFor="cs-grade" error={tried ? errors.grade : ''}><Input id="cs-grade" value={f.grade} onChange={set('grade')} /></Field>
        <Field label="Casting date" htmlFor="cs-date" error={tried ? errors.cast : ''}><Input id="cs-date" type="date" max={today()} value={cast} onChange={(e) => setCast(e.target.value)} /></Field>
        <Field label="Slump (mm)" htmlFor="cs-slump"><NumField id="cs-slump" value={slump} onValue={setSlump} /></Field>
        <Field label="Pour / location" htmlFor="cs-where" className="sm:col-span-2"><Input id="cs-where" value={f.location} placeholder="Raft pour 1, grid A-C" onChange={set('location')} /></Field>
        <Field label="Pour reference" htmlFor="cs-ref"><Input id="cs-ref" value={f.pour_ref} placeholder="P-014" onChange={set('pour_ref')} /></Field>
        <Field label="Cube identification" htmlFor="cs-ids" hint="How each cube is marked" className="sm:col-span-2"><Input id="cs-ids" value={f.cube_ids} placeholder="A1, A2, A3, A4, A5, A6" onChange={set('cube_ids')} /></Field>
        <Field label="Docket no." htmlFor="cs-dock"><Input id="cs-dock" value={f.docket} onChange={set('docket')} /></Field>
        <Field label="RMC plant / mixer" htmlFor="cs-sup" className="sm:col-span-2"><Input id="cs-sup" value={f.supplier} onChange={set('supplier')} /></Field>
        <Field label="Test at (days)" htmlFor="cs-ages" error={tried ? errors.ages : ''} hint={ages.length ? `This project tests ${grade} at ${ages.join(', ')} days. Leave blank to follow it.` : 'No criteria are set for this grade yet - 7 and 28 days unless you say otherwise.'}><Input id="cs-ages" value={f.test_ages} placeholder={ages.join(', ') || '7, 28'} onChange={set('test_ages')} /></Field>
        <Field label="Remarks" htmlFor="cs-rem" className="sm:col-span-3"><Textarea id="cs-rem" rows={2} value={f.remarks} onChange={set('remarks')} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => (bad ? setTried(true) : save.mutate())}>Register the set</Button>
      </div>
    </div>
  )
}

/** One sample: when each test falls due, what each result was read against, the engineer's decision and who did what. */
export function CubeModal({ id, onClose, onNcr, onFiles }: { id: number | null; onClose: () => void; onNcr: (c: CubeSet, age?: number) => void; onFiles: (c: CubeSet) => void }) {
  const q = useCube(id)
  const c = q.data?.cube_set
  return (
    <Modal open={!!id} onOpenChange={(o) => !o && onClose()} title={c ? `${c.number} - ${c.grade}${c.location ? ` - ${c.location}` : ''}` : 'Cube sample'} size="xl">
      {q.isPending && <Skeleton className="h-48 w-full" />}
      {q.isError && <p role="alert" className="text-[13px] text-danger">{q.error.message}</p>}
      {c && <Detail key={`${c.id}-${c.results.length}-${c.acceptance}-${c.status}`} set={c} history={q.data?.history} onClose={onClose} onNcr={onNcr} onFiles={onFiles} />}
    </Modal>
  )
}

const DECISIONS = [{ value: 'accepted', label: 'Accepted' }, { value: 'conditional', label: 'Accepted with conditions' }, { value: 'rejected', label: 'Rejected' }]

function Detail({ set: c, history, onClose, onNcr, onFiles }: { set: CubeSet; history?: import('@/api/quality').HistoryLine[]; onClose: () => void; onNcr: (c: CubeSet, age?: number) => void; onFiles: (c: CubeSet) => void }) {
  const { can } = useSession()
  const [adding, setAdding] = useState(false)
  const [flagging, setFlagging] = useState(false)
  const [deciding, setDeciding] = useState(false)
  const pending = c.schedule.filter((s) => s.state !== 'tested')
  const own = c.ncrs ?? []
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={cubeTone(c.status)} dot>{c.status}</Badge>
        {c.counted_below > 0 && <span className="text-xs text-danger">{c.counted_below} result{c.counted_below === 1 ? '' : 's'} below criteria</span>}
      </div>
      {c.needs_review && (
        <div role="status" className="rounded-lg border border-info/30 bg-info-soft p-3 text-[13px] text-info">
          <p className="font-medium">Needs engineering review</p>
          <ul className="mt-1 list-disc pl-5">{c.review_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      )}
      {c.acceptance && <p role="status" className="rounded-lg border border-border bg-surface p-3 text-[13px]"><span className="font-medium">{DECISIONS.find((d) => d.value === c.acceptance)?.label}</span> by {c.accepted_by} on {formatDate(c.accepted_on)}{c.acceptance_note && <> - {c.acceptance_note}</>}</p>}
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact label="Project">{c.project}</Fact>
        <Fact label="Pour / reference">{[c.location, c.pour_ref].filter(Boolean).join(' - ')}</Fact>
        <Fact label="Cubes">{c.cube_ids}</Fact>
        <Fact label="Casting date">{formatDate(c.cast_on)}</Fact>
        <Fact label="Supplier / docket">{[c.supplier, c.docket && `#${c.docket}`].filter(Boolean).join(' ')}</Fact>
        <Fact label="Slump">{c.slump_mm ? `${c.slump_mm} mm` : ''}</Fact>
        <Fact label="Cast by">{c.cast_by}</Fact>
        <Fact label="Remarks">{c.remarks}</Fact>
      </dl>

      <Section title="Test schedule">
        <ul className="flex flex-wrap gap-2">
          {c.schedule.map((s) => (
            <li key={s.age_days} className={`rounded-md border px-3 py-2 text-[13px] ${s.state === 'overdue' ? 'border-danger/40 text-danger' : s.state === 'due' ? 'border-warning/40 text-warning' : 'border-border'}`}>
              <span className="font-medium">{s.age_days} days</span> - {s.state === 'tested' ? 'tested' : s.state === 'overdue' ? `overdue since ${formatDate(s.due_on)}` : s.state === 'due' ? 'due today' : `due ${formatDate(s.due_on)}`}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Results">
        {c.results.length === 0 ? <p className="text-[13px] text-muted-foreground">No test recorded yet.</p> : (
          <div className="overflow-x-auto">
            <table aria-label="Results" className="w-full min-w-[40rem] text-[13.5px]">
              <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1.5 pr-3">Age</th><th className="pr-3">Tested</th><th className="pr-3">Cubes (MPa)</th><th className="pr-3">Average</th><th className="pr-3">Read against</th><th className="pr-3">Lab</th><th>Outcome</th></tr></thead>
              <tbody>
                {c.results.map((r) => (
                  <tr key={r.id} className="border-t border-border align-top">
                    <td className="py-2 pr-3 font-medium">{r.age_days} d{r.actual_age != null && r.actual_age !== r.age_days && <span className="block text-xs font-normal text-muted-foreground">tested at {r.actual_age} d</span>}</td>
                    <td className="pr-3">{formatDate(r.tested_on)}</td>
                    <td className="pr-3">{r.strengths.join(', ')}{!r.spread_ok && <span title="A cube is more than 15% off the average" className="ml-1 text-warning">!</span>}</td>
                    <td className={`pr-3 font-semibold ${r.failed ? 'text-danger' : ''}`}>{r.average}</td>
                    <td className="pr-3 text-xs text-muted-foreground">{r.evaluation === 'no_criteria' ? 'No approved criteria' : <>avg {r.criteria_min}{r.criteria_single ? `, single ${r.criteria_single}` : ''}<br />{r.criteria_ref}</>}</td>
                    <td className="pr-3">{r.lab}</td>
                    <td><Badge tone={r.evaluation === 'meets' ? 'success' : r.evaluation === 'below' ? 'danger' : 'info'}>{r.evaluation === 'meets' ? 'Meets criteria' : r.evaluation === 'below' ? 'Below criteria' : 'Review'}</Badge>{r.flagged && <span className="ml-1 text-xs text-info">flagged</span>}
                      {r.remarks && <p className="mt-1 max-w-56 whitespace-pre-line text-xs text-muted-foreground">{r.remarks}</p>}
                      {r.failed && can('site.record') && !own.some((n) => n.source_ref === String(r.age_days)) && <Button size="sm" variant="outline" className="mt-1 text-danger" onClick={() => onNcr(c, r.age_days)}>Raise NCR</Button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {own.length > 0 && <p className="mt-2 text-[13px]">Non-conformance: {own.map((n) => `${n.number}${n.source_ref ? ` (${n.source_ref}-day)` : ''}`).join(', ')}</p>}
        <p className="mt-2 text-xs text-muted-foreground">A result is read against the criteria set for this project. It is evidence for the engineer, not a decision: concrete is accepted only by an engineering assessment.</p>
      </Section>

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        <Button variant="outline" onClick={() => onFiles(c)}><FileText /> Test reports</Button>
        {can('site.record') && c.results.length > 0 && <Button variant="outline" onClick={() => setFlagging(true)}>Flag for review</Button>}
        {can('site.signoff') && c.results.length > 0 && <Button variant="outline" onClick={() => setDeciding(true)}>Engineering decision</Button>}
        {can('site.record') && pending.length > 0 && <Button onClick={() => setAdding(true)}>Enter a result</Button>}
        <Button variant="ghost" onClick={onClose}>Close</Button>
      </div>
      <Section title="Sample history"><History lines={history} /></Section>
      <ResultModal set={c} open={adding} onClose={() => setAdding(false)} />
      <FlagDialog set={c} open={flagging} onClose={() => setFlagging(false)} />
      <DecisionModal set={c} open={deciding} onClose={() => setDeciding(false)} />
    </div>
  )
}

/** A crushing result: the age tested at, the strength of each cube, the laboratory and its report. */
function ResultModal({ set: c, open, onClose }: { set: CubeSet; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={`${c.number} ${c.grade} - enter a result`} description="Strengths in N/mm2 (MPa), one per cube. The result is read against this project's criteria for the age.">
      {open && <ResultForm key={c.id} set={c} onClose={onClose} />}
    </Modal>
  )
}

function ResultForm({ set: c, onClose }: { set: CubeSet; onClose: () => void }) {
  const waiting = c.schedule.filter((s) => s.state !== 'tested')
  const [age, setAge] = useState(String(waiting[0]?.age_days ?? 28))
  const [strengths, setStrengths] = useState('')
  const [on, setOn] = useState(today())
  const [lab, setLab] = useState('')
  const [remarks, setRemarks] = useState('')
  const [flag, setFlag] = useState(false)
  const [files, setFiles] = useState<File[]>([])
  const [tried, setTried] = useState(false)
  const vals = (strengths.match(/\d+(?:\.\d+)?/g) ?? []).map(Number)
  const errors = {
    strengths: !vals.length ? 'The strength of each cube, e.g. 31.2, 29.8, 30.5.' : vals.some((v) => v <= 0 || v > 150) ? 'Strengths are in N/mm2, up to 150.' : '',
    on: !on ? 'Give the testing date.' : on > today() ? 'A test cannot be dated in the future.' : on < c.cast_on ? `Before the cubes were cast (${formatDate(c.cast_on)}).` : '',
    age: !age || Number(age) < 1 ? 'Give the age in days.' : c.results.some((r) => r.age_days === Number(age)) ? 'That age already has its result.' : '',
  }
  const bad = Object.values(errors).some(Boolean)
  const save = useAction(
    async () => {
      const r = await cubeResult(c.id, { age_days: Number(age), strengths, tested_on: on, lab, remarks, flag_review: flag })
      let failed: string[] = []
      if (files.length) failed = (await uploadFiles(files, 'cube_set', c.id, { kind: 'document', caption: `${age}-day test report${lab ? ` - ${lab}` : ''}` })).failed
      return { ...r, failed }
    },
    {
      invalidate: [qcKeys.all],
      success: (r) => { const x = r.cube_set.results.find((y) => y.age_days === Number(age)); return `${r.cube_set.number} at ${age} days: ${x?.average} N/mm2 - ${x?.verdict}` },
      onSuccess: (r) => { if (r.failed.length) toast.error(`Result saved, but the report was not: ${r.failed.join(' - ')}`); onClose() },
    },
  )
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Age at test (days)" htmlFor="cr-age" error={tried ? errors.age : ''}>
          <Input id="cr-age" list="cr-ages" inputMode="numeric" value={age} onChange={(e) => setAge(e.target.value.replace(/\D/g, ''))} />
          <datalist id="cr-ages">{waiting.map((s) => <option key={s.age_days} value={s.age_days} />)}</datalist>
        </Field>
        <Field label="Testing date" htmlFor="cr-on" error={tried ? errors.on : ''}><Input id="cr-on" type="date" min={c.cast_on} max={today()} value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Laboratory" htmlFor="cr-lab"><Input id="cr-lab" value={lab} onChange={(e) => setLab(e.target.value)} /></Field>
        <Field label="Compressive strength of each cube (MPa)" htmlFor="cr-str" hint="Separated by commas, e.g. 24.5, 25.1, 26" error={tried ? errors.strengths : ''} className="sm:col-span-3"><Textarea id="cr-str" rows={2} value={strengths} onChange={(e) => setStrengths(e.target.value)} /></Field>
        <Field label="Remarks" htmlFor="cr-rem" className="sm:col-span-3"><Textarea id="cr-rem" rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)} /></Field>
        <div className="sm:col-span-3 grid gap-3">
          <FilePick files={files} onChange={setFiles} label="Attach the test report" accept="application/pdf,image/*" />
          <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={flag} onChange={(e) => setFlag(e.target.checked)} /> Send for engineering review whatever the number says</label>
        </div>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => (bad ? setTried(true) : save.mutate())}>Record it</Button>
      </div>
    </div>
  )
}

function FlagDialog({ set: c, open, onClose }: { set: CubeSet; open: boolean; onClose: () => void }) {
  const flag = useAction((note: string) => flagCube(c.id, note), { invalidate: [qcKeys.all], success: 'Sent for engineering review', onSuccess: onClose })
  return <ConfirmDialog open={open} onOpenChange={(o) => !o && onClose()} title={`Flag ${c.number} for engineering review`} description="It stays in review until the engineer decides." reason={{ label: 'What should the engineer look at', required: true }} confirmLabel="Send for review" loading={flag.isPending} onConfirm={(note) => flag.mutate(note)} />
}

function DecisionModal({ set: c, open, onClose }: { set: CubeSet; open: boolean; onClose: () => void }) {
  const [decision, setDecision] = useState(c.counted_below ? 'conditional' : 'accepted')
  const [note, setNote] = useState('')
  const below = c.counted_below > 0
  const needNote = decision !== 'accepted' || c.review_reasons.length > 0
  const save = useAction(() => decideCube(c.id, decision, note), { invalidate: [qcKeys.all], success: (r) => `${r.cube_set.number}: ${r.cube_set.status}`, onSuccess: onClose })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={`${c.number} - engineering decision`} description="The engineer's assessment of the concrete as a whole, not of one test. It goes on the record with your name.">
      <div className="grid gap-4">
        <Field label="Decision" htmlFor="cd-dec"><Select id="cd-dec" value={decision} onChange={(e) => setDecision(e.target.value)} options={DECISIONS.map((d) => ({ ...d, disabled: d.value === 'accepted' && below }))} /></Field>
        {below && <p className="text-[13px] text-danger">A result is below its criteria, so the set cannot simply be accepted: accept it with conditions (cores, load test) or reject it.</p>}
        <Field label="Basis of the decision" htmlFor="cd-note" hint="What was assessed - all results, mix records, curing, core tests - and why." error={needNote && !note.trim() ? 'Required.' : ''}><Textarea id="cd-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={needNote && !note.trim()} onClick={() => save.mutate()}>Record the decision</Button>
      </div>
    </Modal>
  )
}
