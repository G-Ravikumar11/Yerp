import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Camera, FileText } from 'lucide-react'
import { Badge, Button, Field, Input, Modal } from '@/components/ui'
import { isFault, safetyKeys, signCheck, type Check, type CheckForm } from '@/api/safety'
import { uploadFiles } from '@/api/files'
import { apiUrl } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { toast } from '@/stores/toast'
import { formatDate, today } from '@/lib/format'

const ANSWER_TEXT: Record<string, string> = { yes: 'Yes', no: 'No', na: 'N/A', '': '-' }

/** An inspection read back as it was filled in - the items, photographs, readings and who has signed - with the signatures still to give. */
export function CheckDetail({ check, form, onClose }: { check: Check; form: CheckForm | undefined; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState<Record<string, string>>({})
  const [on, setOn] = useState(today())
  const [busy, setBusy] = useState(false)
  const refresh = { invalidate: [safetyKeys.all] }
  const sign = useAction((v: { role: string; name: string; decision?: string }) => signCheck(check.id, { role: v.role, name: v.name, date: on, decision: v.decision }), { ...refresh, success: 'Signed' })
  const addPhoto = async (key: string, files: FileList | null) => {
    if (!files?.length) return
    setBusy(true)
    const { failed } = await uploadFiles(Array.from(files), 'equipment_check', check.id, { caption: `item:${key}`, kind: 'photo' })
    await qc.invalidateQueries({ queryKey: safetyKeys.all })
    setBusy(false)
    if (failed.length) toast.error(failed[0]!)
    else toast.success('Photo added')
  }
  const sections: { name: string; items: Check['items'] }[] = []
  for (const it of check.items) {
    if (!sections.length || sections[sections.length - 1]!.name !== (it.section ?? '')) sections.push({ name: it.section ?? '', items: [] })
    sections[sections.length - 1]!.items.push(it)
  }
  const fault = check.result === 'fail'
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`${check.number} - ${check.form_label}`} description={`${check.doc_ref} - ${check.project}`} size="xl">
      <div className={'mb-4 flex flex-wrap items-center gap-3 rounded-lg border p-3 ' + (fault ? 'border-danger/40 bg-danger/10' : 'border-success/40 bg-success/10')}>
        <Badge tone={fault ? 'danger' : 'success'} dot>{fault ? 'Fault found' : 'No fault found'}</Badge>
        <p className="text-sm">{fault ? `Do not use ${check.equipment_no} until it is put right${check.failed.length ? ` - item ${check.failed.join(', ')}` : ''}${check.rpm_wrong ? ' - wheel rated below the machine speed' : ''}.` : 'Every item passed.'}</p>
        <Button size="sm" variant="outline" className="ml-auto" asChild><a href={`/api/safety/checks/${check.id}/document.pdf`} target="_blank" rel="noopener"><FileText /> Paper form (PDF)</a></Button>
      </div>

      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <Fact label={form?.equipment_label.replace(/\.$/, '') ?? 'Equipment'} value={check.equipment_no} />
        {check.specs && <Fact label={form?.specs_label.replace(/\.$/, '') || 'Specs'} value={check.specs} />}
        {check.extinguisher_type && <Fact label="Type" value={check.extinguisher_type} />}
        {check.board_type && <Fact label="Type of electrical board" value={check.board_type} />}
        <Fact label="Location" value={check.location} />
        <Fact label="Contractor" value={check.contractor_name} />
        <Fact label="Inspected" value={formatDate(check.inspection_date)} />
        <Fact label="Next inspection" value={check.next_inspection_date ? formatDate(check.next_inspection_date) : '-'} />
        <Fact label="Recorded by" value={check.recorded_by} />
      </dl>

      {sections.map((s) => (
        <section key={s.name || 'items'} className="mt-5">
          {s.name && <h3 className="mb-1 text-sm font-semibold">{s.name}</h3>}
          <ul className="divide-y divide-border rounded-lg border border-border">
            {s.items.map((it) => (
              <li key={it.key} className={'grid gap-1.5 p-3 sm:grid-cols-[1fr_auto] ' + (isFault(it) ? 'bg-danger/10' : '')}>
                <div>
                  <p className="text-sm"><span className="mr-2 font-mono text-[12px] text-muted-foreground">{it.key}</span>{it.label}</p>
                  {it.remarks && <p className="mt-0.5 text-[13px] text-muted-foreground">{it.remarks}</p>}
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    {it.photos.map((p) => <a key={p.id} href={apiUrl(p.url)} target="_blank" rel="noopener"><img src={apiUrl(p.thumb_url)} alt={`Photo of item ${it.key}`} loading="lazy" className="size-14 rounded-md object-cover ring-1 ring-border" /></a>)}
                    <AddPhoto disabled={busy} onPick={(f) => void addPhoto(it.key, f)} />
                  </div>
                </div>
                <div className="flex items-start gap-2 sm:justify-end">
                  <Badge tone={isFault(it) ? 'danger' : it.answer ? 'success' : 'neutral'}>{ANSWER_TEXT[it.answer]}</Badge>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}

      {form && form.readings.length > 0 && (
        <p className="mt-4 text-sm">{form.readings.map((r) => `${r.label}: ${check.readings[r.key] ? `${check.readings[r.key]} ${r.unit}` : '-'}`).join('   ')}</p>
      )}

      <section className="mt-5 rounded-lg border border-border p-3">
        <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
          <h3 className="text-sm font-semibold">Signatures</h3>
          <Field label="Date of signing" htmlFor="cd-on" className="w-44"><Input id="cd-on" type="date" max={today()} value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {(form?.signoffs ?? []).map((s) => {
            const got = check.signoffs[s.role]
            return (
              <div key={s.role} className="rounded-md bg-muted/40 p-2.5">
                <p className="text-[13px] font-medium">{s.label}</p>
                {got ? <p className="text-sm">{got.name} <span className="text-muted-foreground">- {formatDate(got.date)}</span></p> : (
                  <div className="mt-1 flex gap-2">
                    <Input aria-label={`${s.label} - name`} placeholder="Name" value={name[s.role] ?? ''} onChange={(e) => setName((n) => ({ ...n, [s.role]: e.target.value }))} />
                    <Button size="sm" loading={sign.isPending} disabled={!(name[s.role] ?? '').trim()} onClick={() => sign.mutate({ role: s.role, name: name[s.role]! })}>Sign</Button>
                  </div>
                )}
              </div>
            )
          })}
          {form?.review && (
            <div className="rounded-md bg-muted/40 p-2.5">
              <p className="text-[13px] font-medium">{form.review.signoff_label}</p>
              {check.decision ? (
                <p className="text-sm"><Badge tone={check.decision === 'accepted' ? 'success' : 'danger'} dot>{check.decision === 'accepted' ? 'Accepted' : 'Rejected'}</Badge> {check.decision_by} <span className="text-muted-foreground">- {formatDate(check.decision_on)}</span></p>
              ) : (
                <div className="mt-1 grid gap-2">
                  <Input aria-label="Reviewed by - name" placeholder="Name" value={name.review ?? ''} onChange={(e) => setName((n) => ({ ...n, review: e.target.value }))} />
                  <div className="flex gap-2">
                    <Button size="sm" loading={sign.isPending} disabled={!(name.review ?? '').trim() || fault} title={fault ? 'It found a fault, so it cannot be accepted.' : undefined} onClick={() => sign.mutate({ role: 'review', name: name.review!, decision: 'accepted' })}>Accept</Button>
                    <Button size="sm" variant="outline" loading={sign.isPending} disabled={!(name.review ?? '').trim()} onClick={() => sign.mutate({ role: 'review', name: name.review!, decision: 'rejected' })}>Reject</Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
        {sign.error && <p role="alert" className="mt-2 text-[13px] text-danger">{sign.error.message}</p>}
      </section>
    </Modal>
  )
}

const Fact = ({ label, value }: { label: string; value: string }) => (
  <div><dt className="text-xs text-muted-foreground">{label}</dt><dd>{value || '-'}</dd></div>
)

function AddPhoto({ onPick, disabled }: { onPick: (f: FileList | null) => void; disabled: boolean }) {
  const ref = useRef<HTMLInputElement>(null)
  return (
    <>
      <input ref={ref} type="file" accept="image/*" capture="environment" multiple className="sr-only" aria-label="Add a photo of this item" onChange={(e) => { onPick(e.target.files); e.target.value = '' }} />
      <Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => ref.current?.click()}><Camera /> Add photo</Button>
    </>
  )
}
