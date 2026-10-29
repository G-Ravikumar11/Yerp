import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Camera, X } from 'lucide-react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { isFault, recordCheck, safetyKeys, type CheckForm as Form, type CheckInput } from '@/api/safety'
import { uploadFiles } from '@/api/files'
import { toast } from '@/stores/toast'
import { today } from '@/lib/format'

const ANSWERS = [{ v: 'yes', label: 'Yes' }, { v: 'no', label: 'No' }, { v: 'na', label: 'N/A' }] as const

const plusDays = (iso: string, days: number) => {
  const d = new Date(`${iso}T00:00:00`)
  d.setDate(d.getDate() + days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** One checklist, answered item by item: the same items, in the same order, as the company's paper form. */
export function CheckFormModal({ job, forms, open, onClose }: { job: number; forms: Form[]; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="New inspection" description="Answer every item, as on the paper checklist. A fault is flagged as you go." size="xl">
      {open && forms.length > 0 && <InspectionForm job={job} forms={forms} onClose={onClose} />}
    </Modal>
  )
}

/** The segmented Yes / No / N/A of one item. */
function AnswerButtons({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-grid grid-cols-3 gap-0.5 rounded-full border border-border bg-card p-0.5 text-[12px]">
      {ANSWERS.map((a) => (
        <button key={a.v} type="button" role="radio" aria-checked={value === a.v} onClick={() => onChange(value === a.v ? '' : a.v)}
          className={'rounded-md px-2.5 py-1 font-medium transition-colors ' + (value === a.v ? 'bg-[var(--primary)] text-white' : 'text-foreground hover:bg-muted')}>
          {a.label}
        </button>
      ))}
    </div>
  )
}

function InspectionForm({ job, forms, onClose }: { job: number; forms: Form[]; onClose: () => void }) {
  const qc = useQueryClient()
  const [formKey, setFormKey] = useState(forms[0]!.key)
  const form = forms.find((f) => f.key === formKey) ?? forms[0]!
  const [h, setH] = useState({ equipment_no: '', specs: '', location: '', extinguisher_type: '', board_type: '', contractor_name: '', inspection_date: today(), next_inspection_date: '' })
  const [answers, setAnswers] = useState<Record<string, { answer: string; remarks: string }>>({})
  const [photos, setPhotos] = useState<Record<string, File[]>>({})
  const [readings, setReadings] = useState<Record<string, string>>({})
  const [signed, setSigned] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (k: keyof typeof h) => (e: { target: { value: string } }) => setH((x) => ({ ...x, [k]: e.target.value }))

  const pickForm = (key: string) => {
    const next = forms.find((f) => f.key === key)!
    setFormKey(key)
    setAnswers({})
    setPhotos({})
    setReadings({})
    setSigned({})
    // The extinguishers are inspected once a quarter: offer the date, which can be changed.
    setH((x) => ({ ...x, specs: '', extinguisher_type: '', board_type: '', next_inspection_date: next.default_interval_days ? plusDays(x.inspection_date, next.default_interval_days) : '' }))
  }
  const answerOf = (k: string) => answers[k]?.answer ?? ''
  const setAnswer = (k: string, patch: Partial<{ answer: string; remarks: string }>) => setAnswers((a) => ({ ...a, [k]: { answer: a[k]?.answer ?? '', remarks: a[k]?.remarks ?? '', ...patch } }))

  const faults = form.items.filter((i) => isFault({ answer: answerOf(i.key), bad_if_yes: i.bad_if_yes }))
  const rpmWrong = form.key === 'grinder' && Number(readings.wheel_rpm) > 0 && Number(readings.machine_rpm) > 0 && Number(readings.wheel_rpm) < Number(readings.machine_rpm)
  const unanswered = form.items.filter((i) => !i.optional && !answerOf(i.key))
  const needsNext = form.key !== 'electrical'
  const ready = h.equipment_no.trim() && unanswered.length === 0 && (!needsNext || h.next_inspection_date) && (form.key !== 'extinguisher' || h.extinguisher_type)
    && form.readings.every((r) => form.key !== 'grinder' || Number(readings[r.key]) > 0)

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const body: CheckInput = {
        job_id: job, form_type: form.key, ...h,
        items: form.items.map((i) => ({ key: i.key, answer: answerOf(i.key), remarks: answers[i.key]?.remarks ?? '' })),
        readings: Object.fromEntries(form.readings.map((r) => [r.key, Number(readings[r.key]) || 0])),
        signoffs: Object.fromEntries(Object.entries(signed).filter(([, n]) => n.trim()).map(([role, name]) => [role, { name: name.trim(), date: h.inspection_date }])),
      }
      const { check } = await recordCheck(body)
      const failed: string[] = []
      for (const [key, files] of Object.entries(photos)) {
        if (files.length) failed.push(...(await uploadFiles(files, 'equipment_check', check.id, { caption: `item:${key}`, kind: 'photo' })).failed)
      }
      await qc.invalidateQueries({ queryKey: safetyKeys.all })
      if (failed.length) toast.error(`${check.number} saved, but a photo did not go up: ${failed[0]}`)
      else if (check.result === 'fail') toast.error(`${check.number} saved - a fault was found. Do not use ${check.equipment_no} until it is put right.`)
      else toast.success(`${check.number} saved - no fault found`)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Not saved. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const sections: { name: string; items: Form['items'] }[] = []
  for (const it of form.items) {
    const name = it.section ?? ''
    if (!sections.length || sections[sections.length - 1]!.name !== name) sections.push({ name, items: [] })
    sections[sections.length - 1]!.items.push(it)
  }

  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Checklist" htmlFor="ck-form" hint={form.doc_ref} className="sm:col-span-3"><Select id="ck-form" value={formKey} onChange={(e) => pickForm(e.target.value)} options={forms.map((f) => ({ value: f.key, label: f.label }))} /></Field>
        <Field label={form.equipment_label.replace(/\.$/, '')} htmlFor="ck-no"><Input id="ck-no" value={h.equipment_no} autoFocus onChange={set('equipment_no')} /></Field>
        {form.fields.includes('specs') && <Field label={form.specs_label.replace(/\.$/, '')} htmlFor="ck-specs"><Input id="ck-specs" value={h.specs} onChange={set('specs')} /></Field>}
        {form.fields.includes('extinguisher_type') && <Field label="Type" htmlFor="ck-ext"><Select id="ck-ext" value={h.extinguisher_type} placeholder="Choose..." onChange={set('extinguisher_type')} options={(form.extinguisher_types ?? []).map((t) => ({ value: t, label: t }))} /></Field>}
        {form.fields.includes('board_type') && <Field label="Type of electrical board" htmlFor="ck-board"><Input id="ck-board" value={h.board_type} onChange={set('board_type')} /></Field>}
        <Field label="Location" htmlFor="ck-loc"><Input id="ck-loc" value={h.location} onChange={set('location')} /></Field>
        <Field label="Contractor" htmlFor="ck-con"><Input id="ck-con" value={h.contractor_name} onChange={set('contractor_name')} /></Field>
        <Field label="Inspection date" htmlFor="ck-on"><Input id="ck-on" type="date" max={today()} value={h.inspection_date} onChange={(e) => setH((x) => ({ ...x, inspection_date: e.target.value, next_inspection_date: form.default_interval_days && e.target.value ? plusDays(e.target.value, form.default_interval_days) : x.next_inspection_date }))} /></Field>
        <Field label="Next inspection date" htmlFor="ck-next" hint={needsNext ? (form.default_interval_days ? 'Once a quarter, by the HSE plan.' : undefined) : 'Optional for a board.'}><Input id="ck-next" type="date" min={h.inspection_date || undefined} value={h.next_inspection_date} onChange={set('next_inspection_date')} /></Field>
      </div>

      {sections.map((s) => (
        <section key={s.name || 'items'} className="mt-5">
          {s.name && <h3 className="mb-1 text-sm font-semibold">{s.name}</h3>}
          <ul className="divide-y divide-border rounded-lg border border-border">
            {s.items.map((it) => {
              const fault = isFault({ answer: answerOf(it.key), bad_if_yes: it.bad_if_yes })
              const mine = photos[it.key] ?? []
              return (
                <li key={it.key} className={'grid gap-2 p-3 sm:grid-cols-[1fr_auto] ' + (fault ? 'bg-danger/10' : '')}>
                  <div>
                    <p className="text-sm"><span className="mr-2 font-mono text-[12px] text-muted-foreground">{it.key}</span>{it.label}{it.optional && <span className="ml-1 text-xs text-muted-foreground">(optional)</span>}</p>
                    <div className="mt-1.5 grid gap-2 sm:grid-cols-[1fr_auto]">
                      <Input aria-label={`Remarks for item ${it.key}`} placeholder={form.key === 'electrical' ? 'Action required' : 'Remarks'} value={answers[it.key]?.remarks ?? ''} onChange={(e) => setAnswer(it.key, { remarks: e.target.value })} />
                      <PhotoPick id={`ck-photo-${it.key}`} files={mine} onChange={(files) => setPhotos((p) => ({ ...p, [it.key]: files }))} />
                    </div>
                  </div>
                  <div className="flex items-start sm:justify-end"><AnswerButtons label={`Item ${it.key}`} value={answerOf(it.key)} onChange={(v) => setAnswer(it.key, { answer: v })} /></div>
                </li>
              )
            })}
          </ul>
        </section>
      ))}

      {form.readings.length > 0 && (
        <section className="mt-5">
          <h3 className="mb-1 text-sm font-semibold">Readings</h3>
          <div className="grid gap-4 sm:grid-cols-3">
            {form.readings.map((r) => (
              <Field key={r.key} label={`${r.label} (${r.unit})`} htmlFor={`ck-r-${r.key}`}>
                <Input id={`ck-r-${r.key}`} type="number" inputMode="decimal" min={0} value={readings[r.key] ?? ''} onChange={(e) => setReadings((x) => ({ ...x, [r.key]: e.target.value }))} />
              </Field>
            ))}
          </div>
          {rpmWrong && <p role="alert" className="mt-2 text-[13px] font-medium text-danger">The wheel is rated below the machine speed. It can burst: do not use it.</p>}
        </section>
      )}

      <section className="mt-5">
        <h3 className="mb-1 text-sm font-semibold">Signed by</h3>
        <p className="mb-2 text-[13px] text-muted-foreground">Type the name of whoever has checked it. The rest can sign afterwards{form.review ? `, and the ${form.review.label.toLowerCase()} is recorded once the client has looked at it` : ''}.</p>
        <div className="grid gap-4 sm:grid-cols-2">
          {form.signoffs.map((s) => <Field key={s.role} label={s.label} htmlFor={`ck-s-${s.role}`}><Input id={`ck-s-${s.role}`} value={signed[s.role] ?? ''} onChange={(e) => setSigned((x) => ({ ...x, [s.role]: e.target.value }))} /></Field>)}
        </div>
      </section>

      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        <p role={faults.length || rpmWrong ? 'alert' : undefined} className={'mr-auto text-[13px] ' + (faults.length || rpmWrong ? 'font-medium text-danger' : 'text-muted-foreground')}>
          {error || (faults.length || rpmWrong ? `Fault at ${faults.length ? `item ${faults.map((f) => f.key).join(', ')}` : 'the wheel speed'}. Do not use it until it is put right.` : unanswered.length ? `${unanswered.length} item${unanswered.length === 1 ? '' : 's'} still to answer.` : 'Every item answered. No fault.')}
        </p>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={busy} disabled={!ready} onClick={() => void save()}>Save the inspection</Button>
      </div>
    </div>
  )
}

/** A photo of one item: on a phone it opens the camera. */
function PhotoPick({ id, files, onChange }: { id: string; files: File[]; onChange: (f: File[]) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  return (
    <div className="flex items-center gap-1.5">
      <input ref={ref} id={id} type="file" accept="image/*" capture="environment" multiple className="sr-only" aria-label="Photo of this item" onChange={(e) => { onChange([...files, ...Array.from(e.target.files ?? [])]); e.target.value = '' }} />
      <Button type="button" size="sm" variant="outline" onClick={() => ref.current?.click()}><Camera /> {files.length ? `${files.length} photo${files.length === 1 ? '' : 's'}` : 'Photo'}</Button>
      {files.length > 0 && <Button type="button" size="icon" variant="ghost" aria-label="Remove the photos" onClick={() => onChange([])}><X /></Button>}
    </div>
  )
}
