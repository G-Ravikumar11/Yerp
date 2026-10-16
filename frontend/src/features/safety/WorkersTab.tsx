import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Camera, Download, Eye, FileText, Trash2, Upload, UserPlus, X } from 'lucide-react'
import { readPicture } from '@/components/data/PictureField'
import { takePhoto } from '@/lib/mobile'
import { toast } from '@/stores/toast'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Select, Stat, StatGrid, Textarea } from '@/components/ui'
import { removeWorker, screenWorker, useWorkers, workerKeys, type EducationRow, type ExperienceRow, type Worker, type WorkerInput, type WorkerPaper } from '@/api/safety'
import { uploadFiles } from '@/api/files'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { apiUrl } from '@/lib/api'

/** The worker's screening, filled in on the paper form, as a PDF. */
const workerPdf = (id: number) => apiUrl(`/api/workers/${id}/document.pdf`)
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
      width: can('site.signoff') ? '9.5rem' : '6.5rem',
      cell: (w) => (
        <div className="flex items-center justify-end gap-1">
          <Button size="icon" variant="ghost" aria-label={`View ${w.name}`} onClick={() => setViewing(w)}><Eye /></Button>
          <Button size="icon" variant="ghost" asChild><a href={workerPdf(w.id)} target="_blank" rel="noopener" download aria-label={`Download ${w.name}'s screening as PDF`} title="Download PDF"><Download /></a></Button>
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
    mother_tongue: '', other_languages: '', emergency_contact: '', phone: '', identification_mark: '',
    vision_normal: true, vision_problem: '', health_normal: true, health_problem: '',
    weight_kg: '', height_cm: '', blood_group: '',
    certificates_verified: false, trial_briefed: false, safety_officer_name: '',
    pan: '', aadhaar: '',
  })
  const [panCard, setPanCard] = useState<File[]>([])
  const [aadhaarCard, setAadhaarCard] = useState<File[]>([])
  const [signature, setSignature] = useState('')
  const signInput = useRef<HTMLInputElement>(null)
  // The photo of the signature the worker sent, shrunk to a signature's size. Read here, so it is seen before saving.
  const pickSignature = async (file?: File) => {
    if (!file) return
    try { setSignature(await cleanSignature(await readPicture(file, 1200, 800, false))) } catch (e) { toast.error(e instanceof Error ? e.message : 'That picture could not be read') }
  }
  const idWrong = {
    pan: f.pan && !/^[A-Z]{5}\d{4}[A-Z]$/.test(f.pan) ? '5 letters, 4 digits and a letter, like ABCDE1234F.' : '',
    aadhaar: f.aadhaar && !/^[2-9]\d{11}$/.test(f.aadhaar) ? '12 digits, not starting with 0 or 1.' : '',
  }
  // The mobile as the server keeps it: "+91 98765 43210" and "098765 43210" are both 9876543210.
  const phoneDigits = f.phone.replace(/\D/g, '').replace(/^(91|0)(?=\d{10}$)/, '')
  const phoneWrong = f.phone.trim() && !/^[6-9]\d{9}$/.test(phoneDigits) ? 'A 10-digit mobile number, starting with 6, 7, 8 or 9.' : ''
  const phoneShown = phoneDigits.length >= 10 ? phoneWrong : ''
  // Said in red only once the number is typed in full; while it is still being typed the hint is enough.
  const idShown = {
    pan: f.pan.length >= 10 ? idWrong.pan : '',
    aadhaar: f.aadhaar.length >= 12 ? idWrong.aadhaar : '',
  }
  const [education, setEducation] = useState<EducationRow[]>([blankEducation()])
  const [experience, setExperience] = useState<ExperienceRow[]>([blankExperience()])
  const [photo, setPhoto] = useState<File | null>(null)
  const [medical, setMedical] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const age = parseInt(f.age, 10)
  const missing = [
    !f.name.trim() && 'the name',
    !(age >= minAge) && `the age (at least ${minAge})`,
    !f.trade && 'the trade',
    idWrong.pan && 'a correct PAN',
    idWrong.aadhaar && 'a correct Aadhaar number',
    phoneWrong && 'a correct contact number',
  ].filter((x): x is string => !!x)
  const ready = missing.length === 0
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
        emergency_contact: f.emergency_contact, phone: f.phone, identification_mark: f.identification_mark,
        vision_normal: f.vision_normal, vision_problem: f.vision_problem,
        health_normal: f.health_normal, health_problem: f.health_problem,
        weight_kg: Number(f.weight_kg) || 0, height_cm: Number(f.height_cm) || 0, blood_group: f.blood_group,
        education: education.filter((r) => r.exam.trim() || r.school.trim()),
        experience: experience.filter((r) => r.organization.trim() || r.project_site.trim()),
        certificates_verified: f.certificates_verified, trial_briefed: f.trial_briefed,
        safety_officer_name: f.safety_officer_name, pan: f.pan, aadhaar: f.aadhaar, signature,
      }
      const { worker } = await screenWorker(body)
      const failed: string[] = []
      if (photo) failed.push(...(await uploadFiles([photo], 'worker', worker.id, { caption: 'Photo', kind: 'photo' })).failed)
      if (panCard.length) failed.push(...(await uploadFiles(panCard, 'worker', worker.id, { caption: 'PAN card', kind: 'document' })).failed)
      if (aadhaarCard.length) failed.push(...(await uploadFiles(aadhaarCard, 'worker', worker.id, { caption: 'Aadhaar card', kind: 'document' })).failed)
      if (medical.length) failed.push(...(await uploadFiles(medical, 'worker', worker.id, { caption: 'Medical certificate', kind: 'document' })).failed)
      await qc.invalidateQueries({ queryKey: workerKeys.all })
      if (failed.length) toast.error(`${worker.name} screened, but a file did not go up: ${failed[0]}`)
      else toast.withAction(`${worker.name} screened as ${worker.trade.toLowerCase()}`, 'Download PDF', () => window.open(workerPdf(worker.id), '_blank', 'noopener'))
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Not saved. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {/* Laid out as the paper form: Worker ID and date across the top, the person on the left, the photo top right. */}
      <div className="grid gap-4 sm:grid-cols-[1fr_8.5rem]">
        <div className="order-2 grid content-start gap-4 sm:order-1 sm:grid-cols-2">
          <Field label="Worker ID No." htmlFor="wk-id" hint="Given when the screening is saved"><Input id="wk-id" value="" placeholder="WKR-...." disabled /></Field>
          <Field label="Date" htmlFor="wk-on"><Input id="wk-on" type="date" value={f.screened_on} onChange={set('screened_on')} /></Field>
          <Field label="Contractor / Sub-Contractor" htmlFor="wk-contractor" className="sm:col-span-2"><Input id="wk-contractor" value={f.contractor_name} onChange={set('contractor_name')} /></Field>
          <Field label="Full name of the worker" htmlFor="wk-name"><Input id="wk-name" value={f.name} autoFocus onChange={set('name')} /></Field>
          <Field label="Father / Husband's name" htmlFor="wk-father"><Input id="wk-father" value={f.father_name} onChange={set('father_name')} /></Field>
          <Field label="Permanent address" htmlFor="wk-addr" className="sm:col-span-2"><Textarea id="wk-addr" rows={2} value={f.address} onChange={set('address')} /></Field>
        </div>
        <div className="order-1 sm:order-2"><PhotoBox file={photo} onFile={setPhoto} /></div>
      </div>

      <h3 className="mb-2 mt-5 text-sm font-semibold">ID details</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="PAN" htmlFor="wk-pan" hint="Like ABCDE1234F" error={idShown.pan}>
          <div className="flex gap-2">
            <Input id="wk-pan" className="flex-1 uppercase" maxLength={10} placeholder="ABCDE1234F" aria-invalid={!!idShown.pan || undefined} value={f.pan} onChange={(e) => setF((x) => ({ ...x, pan: e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 10) }))} />
            <CardButton what="PAN card" files={panCard} onFiles={setPanCard} />
          </div>
          <CardFiles files={panCard} onFiles={setPanCard} />
        </Field>
        <Field label="Aadhaar" htmlFor="wk-aadhaar" hint="Only the last four digits are shown after saving" error={idShown.aadhaar}>
          <div className="flex gap-2">
            <Input id="wk-aadhaar" className="flex-1" inputMode="numeric" maxLength={14} placeholder="1234 5678 9012" aria-invalid={!!idShown.aadhaar || undefined} value={f.aadhaar.replace(/(\d{4})(?=\d)/g, '$1 ')} onChange={(e) => setF((x) => ({ ...x, aadhaar: e.target.value.replace(/\D/g, '').slice(0, 12) }))} />
            <CardButton what="Aadhaar card" files={aadhaarCard} onFiles={setAadhaarCard} />
          </div>
          <CardFiles files={aadhaarCard} onFiles={setAadhaarCard} />
        </Field>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <Field label="Date of birth" htmlFor="wk-dob"><Input id="wk-dob" type="date" value={f.dob} onChange={set('dob')} /></Field>
        <Field label="Sex" htmlFor="wk-sex"><Select id="wk-sex" value={f.sex} placeholder="Choose..." onChange={set('sex')} options={sexes.map((s) => ({ value: s, label: s }))} /></Field>
        <Field label="Age" htmlFor="wk-age" hint={f.age && age < minAge ? `At least ${minAge}` : undefined}><Input id="wk-age" type="number" inputMode="numeric" min={minAge} max={75} value={f.age} onChange={set('age')} /></Field>
        <Field label="Marital status" htmlFor="wk-marital"><Select id="wk-marital" value={f.marital_status} placeholder="Choose..." onChange={set('marital_status')} options={maritalStatuses.map((s) => ({ value: s, label: s }))} /></Field>
        <Field label="Number of children" htmlFor="wk-children"><Input id="wk-children" type="number" inputMode="numeric" min={0} value={f.children} onChange={set('children')} /></Field>
        <Field label="Mother tongue" htmlFor="wk-tongue"><Input id="wk-tongue" value={f.mother_tongue} onChange={set('mother_tongue')} /></Field>
        <Field label="Other languages known" htmlFor="wk-lang"><Input id="wk-lang" value={f.other_languages} onChange={set('other_languages')} /></Field>
        <Field label="In case of emergency, contact" htmlFor="wk-emerg"><Input id="wk-emerg" value={f.emergency_contact} onChange={set('emergency_contact')} /></Field>
        <Field label="Contact number" htmlFor="wk-phone" hint="The worker's own mobile" error={phoneShown}><Input id="wk-phone" type="tel" inputMode="tel" maxLength={16} placeholder="98765 43210" aria-invalid={!!phoneShown || undefined} value={f.phone} onChange={(e) => setF((x) => ({ ...x, phone: e.target.value.replace(/[^\d+ ]/g, '').slice(0, 16) }))} /></Field>
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

      <h3 className="mb-2 mt-5 text-sm font-semibold">Declaration by the worker</h3>
      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-border p-3">
        <p className="min-w-56 flex-1 text-[13px] text-muted-foreground">The above information given by me is correct to the best of my knowledge.</p>
        <input ref={signInput} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" tabIndex={-1} aria-label="Photo of the worker's signature" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; void pickSignature(f) }} />
        {signature ? (
          <div className="flex items-center gap-3">
            <span className="grid h-16 w-48 place-items-center rounded-md bg-white p-1 ring-1 ring-border"><img src={signature} alt="The worker's signature" className="max-h-full max-w-full" /></span>
            <div className="flex flex-col gap-1">
              <Button size="sm" variant="outline" onClick={() => signInput.current?.click()}><Upload /> Change</Button>
              <Button size="sm" variant="ghost" onClick={() => setSignature('')}>Remove</Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-end gap-1">
            <Button variant="outline" onClick={() => signInput.current?.click()}><Upload /> Upload signature</Button>
            <span className="text-[11px] text-muted-foreground">The photo of the signature the worker sent</span>
          </div>
        )}
      </div>

      <h3 className="mb-2 mt-5 text-sm font-semibold">Verification</h3>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Suitable for employment as (trade)" htmlFor="wk-trade" className="sm:col-span-3"><Select id="wk-trade" value={f.trade} onChange={set('trade')} options={trades.map((t) => ({ value: t, label: t }))} /></Field>
        <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={f.certificates_verified} onChange={(e) => setF((x) => ({ ...x, certificates_verified: e.target.checked }))} /> Certificates / details verified</label>
        <label className="flex items-center gap-1.5 text-sm sm:col-span-2"><input type="checkbox" checked={f.trial_briefed} onChange={(e) => setF((x) => ({ ...x, trial_briefed: e.target.checked }))} /> Seen and briefed the EHS rules of the site</label>
        <Field label="Safety officer" htmlFor="wk-safety" className="sm:col-span-3"><Input id="wk-safety" value={f.safety_officer_name} onChange={set('safety_officer_name')} /></Field>
        <Field label="Medical certificate" htmlFor="wk-med" className="sm:col-span-3" hint="A photo or a PDF. More than one if there are several pages.">
          <Input id="wk-med" type="file" accept="image/*,application/pdf" multiple onChange={(e) => setMedical(Array.from(e.target.files ?? []))} />
        </Field>
      </div>
      {/* Held at the foot of the window: the form is long, and Save has to be in sight wherever the person has scrolled. */}
      <div className="sticky -bottom-5 z-10 -mx-6 -mb-5 mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border bg-popover px-6 py-3">
        {error
          ? <p role="alert" className="mr-auto text-[13px] text-danger">{error}</p>
          : missing.length > 0 && <p className="mr-auto text-[13px] text-muted-foreground">To save, give {missing.join(', ')}.</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={busy} disabled={!ready} onClick={() => void save()}>Save the screening</Button>
      </div>
    </div>
  )
}

/** The passport-size photo box at the top right of the paper form. Shows the picture as soon as it is taken. */
function PhotoBox({ file, onFile }: { file: File | null; onFile: (f: File | null) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const src = useMemo(() => (file ? URL.createObjectURL(file) : ''), [file])
  useEffect(() => () => { if (src) URL.revokeObjectURL(src) }, [src])
  return (
    <div className="flex flex-col items-center gap-1.5">
      <button
        type="button"
        aria-label={file ? 'Change the photo' : 'Add a photo'}
        onClick={() => void takePhoto(input.current, (files) => files[0] && onFile(files[0]))}
        className="grid aspect-[3/4] w-32 place-items-center overflow-hidden rounded-lg border-2 border-dashed border-border bg-muted/40 text-muted-foreground transition-colors hover:border-primary hover:text-primary"
      >
        {src ? <img src={src} alt="The worker's photo" className="size-full object-cover" /> : <span className="flex flex-col items-center gap-1 text-xs font-medium"><Camera className="size-6" />Photo</span>}
      </button>
      <input ref={input} id="wk-photo" type="file" accept="image/*" capture="user" className="sr-only" aria-label="Photo of the worker" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) onFile(f) }} />
      {file
        ? <button type="button" className="text-xs text-muted-foreground hover:text-danger" onClick={() => onFile(null)}>Remove</button>
        : <span className="text-center text-[11px] leading-tight text-subtle">A clear photo of the face. Opens the camera on a phone.</span>}
    </div>
  )
}

/** A phone photo of a signature on paper, made to look signed on the form: the paper made see-through - however grey
 * the light made it - and the picture cut close around the ink, so the signature is not a small mark on a grey patch. */
function cleanSignature(src: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onerror = () => reject(new Error('That picture could not be read'))
    img.onload = () => {
      const c = document.createElement('canvas')
      c.width = img.width
      c.height = img.height
      const ctx = c.getContext('2d')
      if (!ctx) return resolve(src)
      ctx.drawImage(img, 0, 0)
      const shot = ctx.getImageData(0, 0, c.width, c.height)
      const d = shot.data
      const lum = (i: number) => 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]
      // The paper's brightness piece by piece, not one figure for the whole photo: a phone photo is lit unevenly, and
      // a shadowed corner of paper is darker than a pen line in the light. Each piece of a 16 x 16 grid takes the
      // brightness most of it has (the pen line is thin), and the grid is then drawn up to full size, smoothly.
      const cols = 16, rows = 16
      const grid = document.createElement('canvas')
      grid.width = cols
      grid.height = rows
      const g = grid.getContext('2d')
      if (!g) return resolve(src)
      const cells = g.createImageData(cols, rows)
      for (let gy = 0; gy < rows; gy++) {
        for (let gx = 0; gx < cols; gx++) {
          const xs = Math.floor((gx * c.width) / cols), xe = Math.floor(((gx + 1) * c.width) / cols)
          const ys = Math.floor((gy * c.height) / rows), ye = Math.floor(((gy + 1) * c.height) / rows)
          const seen: number[] = []
          for (let y = ys; y < ye; y += 2) for (let x = xs; x < xe; x += 2) seen.push(lum((y * c.width + x) * 4))
          seen.sort((a, b) => a - b)
          const v = seen.length ? seen[Math.floor(seen.length * 0.7)] : 255
          const k = (gy * cols + gx) * 4
          cells.data[k] = cells.data[k + 1] = cells.data[k + 2] = v
          cells.data[k + 3] = 255
        }
      }
      g.putImageData(cells, 0, 0)
      const bgCanvas = document.createElement('canvas')
      bgCanvas.width = c.width
      bgCanvas.height = c.height
      const bgCtx = bgCanvas.getContext('2d')
      if (!bgCtx) return resolve(src)
      bgCtx.imageSmoothingEnabled = true
      bgCtx.drawImage(grid, 0, 0, c.width, c.height)
      const bg = bgCtx.getImageData(0, 0, c.width, c.height).data
      let x0 = c.width, y0 = c.height, x1 = -1, y1 = -1
      for (let y = 0; y < c.height; y++) {
        for (let x = 0; x < c.width; x++) {
          const i = (y * c.width + x) * 4
          const l = lum(i)
          const ink = bg[i] - Math.max(35, bg[i] * 0.2)
          if (l > ink) {
            // Lighter than ink: paper, faded out - fully gone well clear of the ink, softly at its edge.
            d[i + 3] = l > ink + 20 ? 0 : Math.round(255 * (1 - (l - ink) / 20))
          }
          if (d[i + 3] > 128) {
            if (x < x0) x0 = x
            if (x > x1) x1 = x
            if (y < y0) y0 = y
            if (y > y1) y1 = y
          }
        }
      }
      if (x1 < 0) return resolve(src)  // no ink found: keep the photo as it came
      ctx.putImageData(shot, 0, 0)
      const pad = 10
      x0 = Math.max(0, x0 - pad); y0 = Math.max(0, y0 - pad)
      x1 = Math.min(c.width - 1, x1 + pad); y1 = Math.min(c.height - 1, y1 + pad)
      const w = x1 - x0 + 1, h = y1 - y0 + 1
      const scale = Math.min(1, 600 / w, 240 / h)
      const out = document.createElement('canvas')
      out.width = Math.max(1, Math.round(w * scale))
      out.height = Math.max(1, Math.round(h * scale))
      out.getContext('2d')?.drawImage(c, x0, y0, w, h, 0, 0, out.width, out.height)
      resolve(out.toDataURL('image/png'))
    }
    img.src = src
  })
}

const CARD_SIDES = 2  // front and back

/** Beside a card's number: take or choose a photo of the card, front and back. A PDF scan is taken too. */
function CardButton({ what, files, onFiles }: { what: string; files: File[]; onFiles: (f: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const full = files.length >= CARD_SIDES
  const add = (more: File[]) => onFiles([...files, ...more].slice(0, CARD_SIDES))
  return (
    <>
      <Button type="button" variant="outline" size="icon" disabled={full} title={full ? 'Front and back added' : files.length ? `Add the back of the ${what}` : `Photo of the ${what}`} aria-label={files.length ? `Add the back of the ${what}` : `Photo of the ${what}`} onClick={() => void takePhoto(input.current, add)}><Camera /></Button>
      <input ref={input} type="file" accept="image/*,application/pdf" multiple className="sr-only" tabIndex={-1} aria-label={`File of the ${what}`} onChange={(e) => { const picked = Array.from(e.target.files ?? []); e.target.value = ''; if (picked.length) add(picked) }} />
    </>
  )
}

function CardFiles({ files, onFiles }: { files: File[]; onFiles: (f: File[]) => void }) {
  if (!files.length) return null
  return <div className="mt-1 flex flex-wrap gap-2">{files.map((file, i) => <CardThumb key={`${file.name}-${i}`} file={file} side={i === 0 ? 'Front' : 'Back'} onRemove={() => onFiles(files.filter((_, j) => j !== i))} />)}</div>
}

function CardThumb({ file, side, onRemove }: { file: File; side: string; onRemove: () => void }) {
  const image = file.type.startsWith('image/')
  const src = useMemo(() => (image ? URL.createObjectURL(file) : ''), [file, image])
  useEffect(() => () => { if (src) URL.revokeObjectURL(src) }, [src])
  return (
    <span className="relative inline-flex flex-col items-center gap-0.5">
      {image ? <img src={src} alt={`${side} of the card`} className="h-14 w-20 rounded-md object-cover ring-1 ring-border" /> : <span className="grid h-14 w-20 place-items-center rounded-md bg-muted text-muted-foreground ring-1 ring-border"><FileText className="size-5" /></span>}
      <span className="text-[11px] text-muted-foreground">{side}</span>
      <button type="button" aria-label={`Remove the ${side.toLowerCase()} of the card`} onClick={onRemove} className="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full bg-foreground text-background"><X className="size-3" /></button>
    </span>
  )
}

/** A card photo kept on a worker, as a small picture that opens the full one. */
function PaperLinks({ papers }: { papers: WorkerPaper[] }) {
  if (!papers.length) return null
  return (
    <div className="mt-1.5 flex flex-wrap gap-2">
      {papers.map((p, i) => (
        <a key={p.id} href={apiUrl(p.url)} target="_blank" rel="noopener" title={p.name} className="inline-flex flex-col items-center gap-0.5">
          {p.image ? <img src={apiUrl(p.thumb_url)} alt={p.name} className="h-14 w-20 rounded-md object-cover ring-1 ring-border" loading="lazy" /> : <span className="grid h-14 w-20 place-items-center rounded-md bg-muted text-muted-foreground ring-1 ring-border"><FileText className="size-5" /></span>}
          <span className="text-[11px] text-muted-foreground">{papers.length > 1 ? (i === 0 ? 'Front' : 'Back') : 'Open'}</span>
        </a>
      ))}
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
      <div className="grid gap-4 sm:grid-cols-[1fr_8.5rem]">
        <div className="order-1 sm:order-2">
          {w.photo_url ? (
            <a href={apiUrl(w.photo_full_url)} target="_blank" rel="noopener" title="Open the full photo" className="mx-auto block aspect-[3/4] w-32 overflow-hidden rounded-lg ring-1 ring-border">
              <img src={apiUrl(w.photo_url)} alt={`${w.name}'s photo`} className="size-full object-cover" />
            </a>
          ) : (
            <span className="mx-auto grid aspect-[3/4] w-32 place-items-center rounded-lg border-2 border-dashed border-border bg-muted/40 text-center text-xs text-muted-foreground">No photo<br />given</span>
          )}
        </div>
        <div className="order-2 grid min-w-0 content-start gap-3 sm:order-1 sm:grid-cols-3">
          {row('Worker ID No.', w.number)}
          {row('Date', formatDate(w.screened_on))}
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
          {row('Contact number', w.phone)}
          {row('In case of emergency, contact', w.emergency_contact)}
        </div>
      </div>
      {row('Permanent address', w.address) && <div className="mt-4">{row('Permanent address', w.address)}</div>}
      {row('Any other identification mark', w.identification_mark) && <div className="mt-2">{row('Any other identification mark', w.identification_mark)}</div>}

      {(w.pan || w.aadhaar_masked || w.pan_card.length > 0 || w.aadhaar_card.length > 0) && (
        <>
          <h3 className="mb-2 mt-5 text-sm font-semibold">ID details</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <div><div className="text-xs text-muted-foreground">PAN</div><div className="font-mono text-sm">{w.pan || '-'}</div><PaperLinks papers={w.pan_card} /></div>
            <div><div className="text-xs text-muted-foreground">Aadhaar</div><div className="tabular text-sm">{w.aadhaar_masked || '-'}</div><PaperLinks papers={w.aadhaar_card} /></div>
          </div>
        </>
      )}

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

      <h3 className="mb-2 mt-5 text-sm font-semibold">Declaration by the worker</h3>
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <span className="min-w-56 flex-1 text-muted-foreground">The above information given by me is correct to the best of my knowledge.</span>
        {w.signature_url ? (
          <span className="flex flex-col items-center gap-0.5">
            <span className="grid h-16 w-48 place-items-center rounded-md bg-white p-1 ring-1 ring-border"><img src={apiUrl(w.signature_url)} alt={`${w.name}'s signature`} className="max-h-full max-w-full" /></span>
            <span className="text-[11px] text-muted-foreground">Signature uploaded {formatDate(w.signed_at.slice(0, 10))}</span>
          </span>
        ) : <Badge tone="neutral">Not signed</Badge>}
      </div>

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
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        <Button variant="outline" asChild><a href={workerPdf(w.id)} target="_blank" rel="noopener" download><Download /> Download PDF</a></Button>
        <Button variant="ghost" onClick={onClose}>Close</Button>
      </div>
    </Modal>
  )
}
