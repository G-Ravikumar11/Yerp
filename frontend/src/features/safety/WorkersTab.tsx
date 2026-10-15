import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Eye, FileText, Trash2, UserPlus } from 'lucide-react'
import { toast } from '@/stores/toast'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Select, Stat, StatGrid, Textarea } from '@/components/ui'
import { removeWorker, screenWorker, useWorkers, workerKeys, type EducationRow, type ExperienceRow, type Worker, type WorkerInput } from '@/api/safety'
import { uploadFiles } from '@/api/files'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { apiUrl } from '@/lib/api'

const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join('') || '?'

/** The Workers tab: every worker screened before starting on site - who they are, their trade, photo and medical certificate. */
export function WorkersTab() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const [screening, setScreening] = useState(false)
  const [removing, setRemoving] = useState<Worker | null>(null)
  const [viewing, setViewing] = useState<Worker | null>(null)
  const q = useWorkers(job)
  const d = q.data
  const s = d?.summary
  const remove = useAction((w: Worker) => removeWorker(w.id), { invalidate: [workerKeys.all], onSuccess: () => setRemoving(null) })

  const columns: TableColumn<Worker>[] = [
    { id: 'sn', header: 'S.No.', width: '4rem', cell: (w) => <span className="tabular text-muted-foreground">{(d?.workers.indexOf(w) ?? 0) + 1}</span> },
    {
      id: 'who',
      header: 'Worker',
      cell: (w) => (
        <button type="button" className="flex items-center gap-3 text-left" onClick={() => setViewing(w)}>
          {w.photo_url ? (
            <img src={apiUrl(w.photo_url)} alt={`${w.name}'s photo`} className="size-10 shrink-0 rounded-full object-cover ring-1 ring-border" loading="lazy" />
          ) : (
            <span className="grid size-10 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-muted-foreground" title="No photo yet">{initials(w.name)}</span>
          )}
          <div className="min-w-0">
            <div className="font-medium hover:underline">{w.name}</div>
            <div className="font-mono text-xs text-muted-foreground">{w.number}</div>
          </div>
        </button>
      ),
    },
    { id: 'age', header: 'Age', width: '4.5rem', sort: (w) => w.age, cell: (w) => <span className="tabular">{w.age}</span> },
    { id: 'trade', header: 'Trade', sort: (w) => w.trade, cell: (w) => <Badge tone={w.trade.includes('helper') || w.trade.startsWith('Unskilled') ? 'neutral' : 'info'}>{w.trade}</Badge> },
    { id: 'addr', header: 'Address', hideBelow: 'lg', cell: (w) => <span className="line-clamp-2 max-w-64 text-muted-foreground">{w.address || '-'}</span> },
    {
      id: 'med',
      header: 'Medical certificate',
      cell: (w) =>
        w.medical.length ? (
          <div className="flex flex-col gap-0.5">
            {w.medical.map((m) => (
              <a key={m.id} href={apiUrl(m.url)} target="_blank" rel="noopener" className="inline-flex items-center gap-1 text-[13px] text-primary hover:underline">
                <FileText className="size-3.5" /> <span className="max-w-40 truncate">{m.name}</span>
              </a>
            ))}
          </div>
        ) : (
          <Badge tone="warning" dot>Not given</Badge>
        ),
    },
    { id: 'on', header: 'Screened', hideBelow: 'md', sort: (w) => w.screened_on, cell: (w) => <div>{formatDate(w.screened_on)}{w.screened_by && <div className="text-xs text-muted-foreground">by {w.screened_by}</div>}</div> },
    {
      id: 'actions',
      header: '',
      align: 'right',
      width: can('site.signoff') ? '6.5rem' : '3.5rem',
      cell: (w) => (
        <div className="flex items-center justify-end gap-1">
          <Button size="icon" variant="ghost" aria-label={`View ${w.name}`} onClick={() => setViewing(w)}><Eye /></Button>
          {can('site.signoff') && <Button size="icon" variant="ghost" aria-label={`Remove ${w.name}`} onClick={() => setRemoving(w)}><Trash2 /></Button>}
        </div>
      ),
    },
  ]

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="min-w-64 flex-1 sm:max-w-md"><ProjectPicker value={job} onChange={setJob} id="wk-job" allowAll /></div>
        <Button className="ml-auto" disabled={!job} title={job ? undefined : 'Pick a project first'} onClick={() => setScreening(true)}><UserPlus /> Add worker</Button>
      </div>
      <StatGrid className="lg:grid-cols-2 xl:grid-cols-2">
        <Stat label="Workers added" value={s?.workers ?? 0} loading={q.isPending} />
        <Stat label="Without a medical certificate" value={s?.without_medical ?? 0} tone={s?.without_medical ? 'warning' : undefined} loading={q.isPending} />
      </StatGrid>
      {d && d.workers.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2" aria-label="Workers by trade">
          {d.trades.map((t) => (
            <span key={t} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs">
              {t} <span className="tabular font-semibold">{s?.by_trade[t] ?? 0}</span>
            </span>
          ))}
        </div>
      )}
      <DataTable label="Workers" rows={d?.workers ?? []} columns={columns} rowKey={(w) => w.id} loading={q.isPending} empty={job ? 'Nobody screened on this project yet. Screen each worker before they start.' : 'Nobody screened yet. Pick a project and screen each worker before they start.'} />

      <ScreeningModal job={job} trades={d?.trades ?? []} minAge={d?.min_age ?? 18} sexes={d?.sexes ?? []} maritalStatuses={d?.marital_statuses ?? []} open={screening} onClose={() => setScreening(false)} />
      <WorkerDetailModal worker={viewing} open={!!viewing} onClose={() => setViewing(null)} />
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={removing ? `Remove ${removing.name}?` : ''}
        description="Their photo and medical certificate go with them. It cannot be undone."
        confirmLabel="Remove"
        tone="danger"
        loading={remove.isPending}
        onConfirm={() => { if (removing) remove.mutate(removing) }}
      />
    </div>
  )
}

const blankEducation = (): EducationRow => ({ exam: '', year: '', school: '' })
const blankExperience = (): ExperienceRow => ({ organization: '', project_site: '', category: '', period: '', salary: '' })

/** The screening form: the company's own "Screening Of Worker" paper form, field for field - who they are, their
 * physical and education details, previous work, then the photo and the medical certificate. */
function ScreeningModal({ job, trades, minAge, sexes, maritalStatuses, open, onClose }: { job: number; trades: string[]; minAge: number; sexes: string[]; maritalStatuses: string[]; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Screening form" description="Screen every worker before they start on site." size="xl">
      {open && <ScreeningForm job={job} trades={trades} minAge={minAge} sexes={sexes} maritalStatuses={maritalStatuses} onClose={onClose} />}
    </Modal>
  )
}

function ScreeningForm({ job, trades, minAge, sexes, maritalStatuses, onClose }: { job: number; trades: string[]; minAge: number; sexes: string[]; maritalStatuses: string[]; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({
    name: '', age: '', address: '', trade: trades[0] ?? '', screened_on: today(),
    contractor_name: '', father_name: '', dob: '', sex: '', marital_status: '', children: '0',
    mother_tongue: '', other_languages: '', emergency_contact: '', identification_mark: '',
    vision_normal: true, vision_problem: '', health_normal: true, health_problem: '',
    weight_kg: '', height_cm: '', blood_group: '',
    certificates_verified: false, trial_briefed: false, safety_officer_name: '',
  })
  const [education, setEducation] = useState<EducationRow[]>([blankEducation()])
  const [experience, setExperience] = useState<ExperienceRow[]>([blankExperience()])
  const [photo, setPhoto] = useState<File | null>(null)
  const [medical, setMedical] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const age = parseInt(f.age, 10)
  const ready = f.name.trim() && age >= minAge && f.trade
  const editEdu = (i: number, patch: Partial<EducationRow>) => setEducation((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const editExp = (i: number, patch: Partial<ExperienceRow>) => setExperience((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const body: WorkerInput = {
        job_id: job, name: f.name.trim(), age, address: f.address, trade: f.trade, screened_on: f.screened_on,
        contractor_name: f.contractor_name, father_name: f.father_name, dob: f.dob, sex: f.sex,
        marital_status: f.marital_status, children: parseInt(f.children, 10) || 0,
        mother_tongue: f.mother_tongue, other_languages: f.other_languages,
        emergency_contact: f.emergency_contact, identification_mark: f.identification_mark,
        vision_normal: f.vision_normal, vision_problem: f.vision_problem,
        health_normal: f.health_normal, health_problem: f.health_problem,
        weight_kg: Number(f.weight_kg) || 0, height_cm: Number(f.height_cm) || 0, blood_group: f.blood_group,
        education: education.filter((r) => r.exam.trim() || r.school.trim()),
        experience: experience.filter((r) => r.organization.trim() || r.project_site.trim()),
        certificates_verified: f.certificates_verified, trial_briefed: f.trial_briefed,
        safety_officer_name: f.safety_officer_name,
      }
      const { worker } = await screenWorker(body)
      const failed: string[] = []
      if (photo) failed.push(...(await uploadFiles([photo], 'worker', worker.id, { caption: 'Photo', kind: 'photo' })).failed)
      if (medical.length) failed.push(...(await uploadFiles(medical, 'worker', worker.id, { caption: 'Medical certificate', kind: 'document' })).failed)
      await qc.invalidateQueries({ queryKey: workerKeys.all })
      if (failed.length) toast.error(`${worker.name} screened, but a file did not go up: ${failed[0]}`)
      else toast.success(`${worker.name} screened as ${worker.trade.toLowerCase()}`)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Not saved. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">Who they are</h3>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Contractor / Sub-Contractor" htmlFor="wk-contractor" className="sm:col-span-3"><Input id="wk-contractor" value={f.contractor_name} onChange={set('contractor_name')} /></Field>
        <Field label="Full name of the worker" htmlFor="wk-name" className="sm:col-span-2"><Input id="wk-name" value={f.name} autoFocus onChange={set('name')} /></Field>
        <Field label="Father / Husband's name" htmlFor="wk-father"><Input id="wk-father" value={f.father_name} onChange={set('father_name')} /></Field>
        <Field label="Permanent address" htmlFor="wk-addr" className="sm:col-span-3"><Textarea id="wk-addr" rows={2} value={f.address} onChange={set('address')} /></Field>
        <Field label="Date of birth" htmlFor="wk-dob"><Input id="wk-dob" type="date" value={f.dob} onChange={set('dob')} /></Field>
        <Field label="Sex" htmlFor="wk-sex"><Select id="wk-sex" value={f.sex} placeholder="Choose..." onChange={set('sex')} options={sexes.map((s) => ({ value: s, label: s }))} /></Field>
        <Field label="Age" htmlFor="wk-age" hint={f.age && age < minAge ? `At least ${minAge}` : undefined}><Input id="wk-age" type="number" inputMode="numeric" min={minAge} max={75} value={f.age} onChange={set('age')} /></Field>
        <Field label="Marital status" htmlFor="wk-marital"><Select id="wk-marital" value={f.marital_status} placeholder="Choose..." onChange={set('marital_status')} options={maritalStatuses.map((s) => ({ value: s, label: s }))} /></Field>
        <Field label="Number of children" htmlFor="wk-children"><Input id="wk-children" type="number" inputMode="numeric" min={0} value={f.children} onChange={set('children')} /></Field>
        <Field label="Mother tongue" htmlFor="wk-tongue"><Input id="wk-tongue" value={f.mother_tongue} onChange={set('mother_tongue')} /></Field>
        <Field label="Other languages known" htmlFor="wk-lang"><Input id="wk-lang" value={f.other_languages} onChange={set('other_languages')} /></Field>
        <Field label="In case of emergency, contact" htmlFor="wk-emerg"><Input id="wk-emerg" value={f.emergency_contact} onChange={set('emergency_contact')} /></Field>
        <Field label="Any other identification mark" htmlFor="wk-mark" className="sm:col-span-3"><Input id="wk-mark" value={f.identification_mark} onChange={set('identification_mark')} /></Field>
      </div>

      <h3 className="mb-2 mt-5 text-sm font-semibold">Health and physical details</h3>
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="flex items-center gap-2 sm:col-span-1">
          <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={f.vision_normal} onChange={(e) => setF((x) => ({ ...x, vision_normal: e.target.checked }))} /> Vision normal</label>
        </div>
        {!f.vision_normal && <Field label="Vision problem" htmlFor="wk-vision-p" className="sm:col-span-2"><Input id="wk-vision-p" value={f.vision_problem} onChange={set('vision_problem')} /></Field>}
        <div className="flex items-center gap-2 sm:col-span-1">
          <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={f.health_normal} onChange={(e) => setF((x) => ({ ...x, health_normal: e.target.checked }))} /> Health normal</label>
        </div>
        {!f.health_normal && <Field label="Health problem" htmlFor="wk-health-p" className="sm:col-span-2"><Input id="wk-health-p" value={f.health_problem} onChange={set('health_problem')} /></Field>}
        <Field label="Weight (kg)" htmlFor="wk-weight"><Input id="wk-weight" type="number" inputMode="decimal" value={f.weight_kg} onChange={set('weight_kg')} /></Field>
        <Field label="Height (cm)" htmlFor="wk-height"><Input id="wk-height" type="number" inputMode="decimal" value={f.height_cm} onChange={set('height_cm')} /></Field>
        <Field label="Blood group" htmlFor="wk-blood"><Input id="wk-blood" value={f.blood_group} onChange={set('blood_group')} /></Field>
      </div>

      <h3 className="mb-2 mt-5 text-sm font-semibold">Education details</h3>
      <div className="grid gap-2">
        {education.map((r, i) => (
          <div key={i} className="grid grid-cols-3 gap-2">
            <Input aria-label={`Examination passed ${i + 1}`} placeholder="Examination passed" value={r.exam} onChange={(e) => editEdu(i, { exam: e.target.value })} />
            <Input aria-label={`Year ${i + 1}`} placeholder="Year" value={r.year} onChange={(e) => editEdu(i, { year: e.target.value })} />
            <Input aria-label={`School / Board ${i + 1}`} placeholder="School / Board" value={r.school} onChange={(e) => editEdu(i, { school: e.target.value })} />
          </div>
        ))}
      </div>
      <Button size="sm" variant="ghost" className="mt-1" onClick={() => setEducation([...education, blankEducation()])}>Add a line</Button>

      <h3 className="mb-2 mt-5 text-sm font-semibold">Previous work experience</h3>
      <div className="grid gap-2">
        {experience.map((r, i) => (
          <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            <Input aria-label={`Organization ${i + 1}`} placeholder="Organization" value={r.organization} onChange={(e) => editExp(i, { organization: e.target.value })} />
            <Input aria-label={`Project site ${i + 1}`} placeholder="Project site" value={r.project_site} onChange={(e) => editExp(i, { project_site: e.target.value })} />
            <Input aria-label={`Category ${i + 1}`} placeholder="Category" value={r.category} onChange={(e) => editExp(i, { category: e.target.value })} />
            <Input aria-label={`Period ${i + 1}`} placeholder="Period" value={r.period} onChange={(e) => editExp(i, { period: e.target.value })} />
            <Input aria-label={`Salary / wage ${i + 1}`} placeholder="Salary / wage" value={r.salary} onChange={(e) => editExp(i, { salary: e.target.value })} />
          </div>
        ))}
      </div>
      <Button size="sm" variant="ghost" className="mt-1" onClick={() => setExperience([...experience, blankExperience()])}>Add a line</Button>

      <h3 className="mb-2 mt-5 text-sm font-semibold">Verification</h3>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Suitable for employment as (trade)" htmlFor="wk-trade" className="sm:col-span-2"><Select id="wk-trade" value={f.trade} onChange={set('trade')} options={trades.map((t) => ({ value: t, label: t }))} /></Field>
        <Field label="Screened on" htmlFor="wk-on"><Input id="wk-on" type="date" value={f.screened_on} onChange={set('screened_on')} /></Field>
        <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={f.certificates_verified} onChange={(e) => setF((x) => ({ ...x, certificates_verified: e.target.checked }))} /> Certificates / details verified</label>
        <label className="flex items-center gap-1.5 text-sm sm:col-span-2"><input type="checkbox" checked={f.trial_briefed} onChange={(e) => setF((x) => ({ ...x, trial_briefed: e.target.checked }))} /> Seen and briefed the EHS rules of the site</label>
        <Field label="Safety officer" htmlFor="wk-safety" className="sm:col-span-3"><Input id="wk-safety" value={f.safety_officer_name} onChange={set('safety_officer_name')} /></Field>
        <Field label="Picture" htmlFor="wk-photo" className="sm:col-span-3" hint="A clear photo of the face. On a phone this opens the camera.">
          <Input id="wk-photo" type="file" accept="image/*" capture="user" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
        </Field>
        <Field label="Medical certificate" htmlFor="wk-med" className="sm:col-span-3" hint="A photo or a PDF. More than one if there are several pages.">
          <Input id="wk-med" type="file" accept="image/*,application/pdf" multiple onChange={(e) => setMedical(Array.from(e.target.files ?? []))} />
        </Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {error && <p role="alert" className="mr-auto text-[13px] text-danger">{error}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={busy} disabled={!ready} onClick={() => void save()}>Save the screening</Button>
      </div>
    </div>
  )
}

/** Every field of a screened worker, read back exactly as it was entered - the same form, laid out to look at
 * rather than to type into. */
function WorkerDetailModal({ worker: w, open, onClose }: { worker: Worker | null; open: boolean; onClose: () => void }) {
  if (!w) return <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Worker" />
  const row = (label: string, value: string | number | undefined) => (value || value === 0) && String(value).trim() !== '' ? (
    <div><div className="text-xs text-muted-foreground">{label}</div><div className="text-sm">{value}</div></div>
  ) : null
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={w.name} description={`${w.number} - screened ${formatDate(w.screened_on)}${w.screened_by ? ` by ${w.screened_by}` : ''}`} size="xl">
      <div className="flex flex-wrap items-start gap-4">
        {w.photo_url ? (
          <img src={apiUrl(w.photo_url)} alt={`${w.name}'s photo`} className="size-24 shrink-0 rounded-lg object-cover ring-1 ring-border" />
        ) : (
          <span className="grid size-24 shrink-0 place-items-center rounded-lg bg-muted text-lg font-semibold text-muted-foreground">{initials(w.name)}</span>
        )}
        <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-3">
          {row('Contractor / Sub-Contractor', w.contractor_name)}
          {row("Father / Husband's name", w.father_name)}
          {row('Trade', w.trade)}
          {row('Date of birth', w.dob)}
          {row('Sex', w.sex)}
          {row('Age', w.age)}
          {row('Marital status', w.marital_status)}
          {row('Number of children', w.children)}
          {row('Mother tongue', w.mother_tongue)}
          {row('Other languages known', w.other_languages)}
          {row('In case of emergency, contact', w.emergency_contact)}
        </div>
      </div>
      {row('Permanent address', w.address) && <div className="mt-4">{row('Permanent address', w.address)}</div>}
      {row('Any other identification mark', w.identification_mark) && <div className="mt-2">{row('Any other identification mark', w.identification_mark)}</div>}

      <h3 className="mb-2 mt-5 text-sm font-semibold">Health and physical details</h3>
      <div className="grid gap-3 sm:grid-cols-3">
        {row('Vision', w.vision_normal ? 'Normal' : w.vision_problem || 'Not normal')}
        {row('Health', w.health_normal ? 'Normal' : w.health_problem || 'Not normal')}
        {row('Weight', w.weight_kg ? `${w.weight_kg} kg` : undefined)}
        {row('Height', w.height_cm ? `${w.height_cm} cm` : undefined)}
        {row('Blood group', w.blood_group)}
      </div>

      {w.education.length > 0 && (
        <>
          <h3 className="mb-2 mt-5 text-sm font-semibold">Education details</h3>
          <table className="w-full text-left text-[13px]"><thead className="text-xs text-muted-foreground"><tr><th className="py-1 pr-2 font-medium">Examination passed</th><th className="px-2 font-medium">Year</th><th className="px-2 font-medium">School / Board</th></tr></thead>
            <tbody>{w.education.map((r, i) => <tr key={i} className="border-t border-border"><td className="py-1.5 pr-2">{r.exam}</td><td className="px-2">{r.year}</td><td className="px-2">{r.school}</td></tr>)}</tbody></table>
        </>
      )}

      {w.experience.length > 0 && (
        <>
          <h3 className="mb-2 mt-5 text-sm font-semibold">Previous work experience</h3>
          <table className="w-full text-left text-[13px]"><thead className="text-xs text-muted-foreground"><tr><th className="py-1 pr-2 font-medium">Organization</th><th className="px-2 font-medium">Project site</th><th className="px-2 font-medium">Category</th><th className="px-2 font-medium">Period</th><th className="pl-2 font-medium">Salary / wage</th></tr></thead>
            <tbody>{w.experience.map((r, i) => <tr key={i} className="border-t border-border"><td className="py-1.5 pr-2">{r.organization}</td><td className="px-2">{r.project_site}</td><td className="px-2">{r.category}</td><td className="px-2">{r.period}</td><td className="pl-2">{r.salary}</td></tr>)}</tbody></table>
        </>
      )}

      <h3 className="mb-2 mt-5 text-sm font-semibold">Verification</h3>
      <div className="grid gap-2 text-sm">
        <div className="flex items-center gap-2"><Badge tone={w.certificates_verified ? 'success' : 'neutral'}>{w.certificates_verified ? 'Verified' : 'Not verified'}</Badge> Certificates / details</div>
        <div className="flex items-center gap-2"><Badge tone={w.trial_briefed ? 'success' : 'neutral'}>{w.trial_briefed ? 'Briefed' : 'Not yet'}</Badge> Seen and briefed the EHS rules of the site</div>
        {row('Safety officer', w.safety_officer_name)}
      </div>

      {w.medical.length > 0 && (
        <div className="mt-4"><p className="mb-1 text-xs text-muted-foreground">Medical certificate</p>
          <div className="flex flex-wrap gap-2">{w.medical.map((m) => <a key={m.id} href={apiUrl(m.url)} target="_blank" rel="noopener" className="inline-flex items-center gap-1 text-[13px] text-primary hover:underline"><FileText className="size-3.5" /> {m.name}</a>)}</div>
        </div>
      )}
      <div className="mt-5 flex items-center justify-end border-t border-border pt-4"><Button variant="ghost" onClick={onClose}>Close</Button></div>
    </Modal>
  )
}
