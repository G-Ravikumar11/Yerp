import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select, Skeleton, Tabs } from '@/components/ui'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { deleteCriteria, deleteTemplate, qcKeys, saveCriteria, saveTemplate, useCriteria, useTemplates, type Criteria, type Template } from '@/api/quality'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'

/** What the quality records are read against: the checklists and the approved acceptance criteria. Kept by those who sign off. */
export function SetupModal({ job, open, onClose }: { job: number; open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<'checklists' | 'criteria'>('checklists')
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Checklists and acceptance criteria" description="Taken from the approved project specification. Records already made keep what they were read against." size="xl">
      <div className="mb-4"><Tabs label="Set-up" value={tab} onChange={setTab} items={[{ value: 'checklists', label: 'Checklists' }, { value: 'criteria', label: 'Concrete criteria' }]} /></div>
      {open && tab === 'checklists' && <Checklists job={job} />}
      {open && tab === 'criteria' && <CriteriaList job={job} />}
    </Modal>
  )
}

function Checklists({ job }: { job: number }) {
  const { can } = useSession()
  const q = useTemplates(job, true)
  const [edit, setEdit] = useState<Template | 'new' | null>(null)
  const [drop, setDrop] = useState<Template | null>(null)
  const remove = useAction((t: Template) => deleteTemplate(t.id!), { invalidate: [qcKeys.all], success: 'Checklist removed', onSuccess: () => setDrop(null) })
  if (q.isPending) return <Skeleton className="h-32 w-full" />
  const manage = can('site.signoff')
  if (edit) return <TemplateForm key={edit === 'new' ? 'new' : (edit.id ?? edit.name)} template={edit === 'new' ? null : edit} job={job} onDone={() => setEdit(null)} />
  return (
    <div>
      {manage && <div className="mb-3 flex justify-end"><Button size="sm" onClick={() => setEdit('new')}><Plus /> New checklist</Button></div>}
      <ul className="grid gap-2">
        {(q.data ?? []).map((t) => (
          <li key={`${t.id ?? 'std'}-${t.name}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-3 text-[13.5px]">
            <div className="min-w-0 flex-1">
              <p className="font-medium">{t.name} <span className="font-normal text-muted-foreground">- {t.items.length} items</span></p>
              <p className="text-xs text-muted-foreground">{t.work_type}{t.spec_ref && ` - ${t.spec_ref}`}{t.job_id ? ' - this project only' : ''}</p>
            </div>
            {t.builtin ? <Badge>Standard</Badge> : !t.is_active ? <Badge tone="warning">Switched off</Badge> : <Badge tone="ember">Company</Badge>}
            {manage && <Button size="sm" variant="outline" onClick={() => setEdit(t)}>{t.builtin ? 'Customise' : 'Edit'}</Button>}
            {manage && !t.builtin && <Button size="sm" variant="ghost" aria-label={`Remove ${t.name}`} onClick={() => setDrop(t)}><Trash2 /></Button>}
          </li>
        ))}
      </ul>
      {!manage && <p className="mt-3 text-xs text-muted-foreground">Checklists are kept by those who sign off site work.</p>}
      <ConfirmDialog open={!!drop} onOpenChange={(o) => !o && setDrop(null)} title={`Remove ${drop?.name ?? ''}?`} description="Inspections already started keep their own copy of the items." tone="danger" confirmLabel="Remove" loading={remove.isPending} onConfirm={() => { if (drop) remove.mutate(drop) }} />
    </div>
  )
}

function TemplateForm({ template: t, job, onDone }: { template: Template | null; job: number; onDone: () => void }) {
  // Customising a standard list starts from its items but makes a new company list with the same name.
  const [name, setName] = useState(t?.name ?? '')
  const [work, setWork] = useState(t?.work_type ?? '')
  const [spec, setSpec] = useState(t?.spec_ref ?? '')
  const [scope, setScope] = useState<number | null>(t?.job_id ?? null)
  const [active, setActive] = useState(t?.is_active ?? true)
  const [items, setItems] = useState(() => (t?.items.length ? t.items.map((x) => ({ ...x })) : [{ item: '', criteria: '' }]))
  const [tried, setTried] = useState(false)
  const id = t && !t.builtin ? t.id : null
  const clean = items.filter((x) => x.item.trim())
  const errors = { name: name.trim() ? '' : 'Give the checklist a name.', items: clean.length ? '' : 'Add at least one item to check.' }
  const bad = Object.values(errors).some(Boolean)
  const save = useAction(() => saveTemplate(id, { name, work_type: work, job_id: scope, spec_ref: spec, items: clean, is_active: active }), { invalidate: [qcKeys.all], success: 'Checklist saved', onSuccess: onDone })
  const edit = (n: number, patch: Partial<(typeof items)[number]>) => setItems((l) => l.map((x, k) => (k === n ? { ...x, ...patch } : x)))
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor="tf-name" error={tried ? errors.name : ''}><Input id="tf-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Kind of work" htmlFor="tf-work"><Input id="tf-work" value={work} placeholder="Concrete, Brickwork, Flooring..." onChange={(e) => setWork(e.target.value)} /></Field>
        <Field label="Specification reference" htmlFor="tf-spec"><Input id="tf-spec" value={spec} placeholder="Spec section 03300 cl. 3.4" onChange={(e) => setSpec(e.target.value)} /></Field>
        <Field label="Applies to" htmlFor="tf-scope"><Select id="tf-scope" value={scope ?? ''} onChange={(e) => setScope(Number(e.target.value) || null)} options={[{ value: '', label: 'Every project' }, ...(job ? [{ value: job, label: 'The selected project only' }] : [])]} /></Field>
      </div>
      <div className="mt-4">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Items and what each must meet</p>
        <ul className="grid gap-2">
          {items.map((x, n) => (
            <li key={n} className="grid grid-cols-[1fr_auto] gap-2 sm:grid-cols-[2fr_2fr_auto]">
              <Input aria-label={`Item ${n + 1}`} placeholder="What is checked" value={x.item} onChange={(e) => edit(n, { item: e.target.value })} />
              <Input aria-label={`Acceptance criterion ${n + 1}`} className="max-sm:order-3 max-sm:col-span-2" placeholder="Acceptance criterion (from the specification)" value={x.criteria} onChange={(e) => edit(n, { criteria: e.target.value })} />
              <Button variant="ghost" size="sm" aria-label={`Remove item ${n + 1}`} onClick={() => setItems((l) => l.filter((_, k) => k !== n))}><Trash2 /></Button>
            </li>
          ))}
        </ul>
        {tried && errors.items && <p role="alert" className="mt-1 text-xs text-danger">{errors.items}</p>}
        <Button className="mt-2" size="sm" variant="outline" onClick={() => setItems((l) => [...l, { item: '', criteria: '' }])}><Plus /> Add an item</Button>
      </div>
      {id && <label className="mt-4 flex items-center gap-2 text-[13px]"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> In use (untick to stop offering it)</label>}
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => (bad ? setTried(true) : save.mutate())}>Save checklist</Button>
      </div>
    </div>
  )
}

function CriteriaList({ job: initial }: { job: number }) {
  const { can } = useSession()
  const [job, setJob] = useState(initial)
  const q = useCriteria(job)
  const [edit, setEdit] = useState<Criteria | 'new' | null>(null)
  const [drop, setDrop] = useState<Criteria | null>(null)
  const remove = useAction((c: Criteria) => deleteCriteria(c.id), { invalidate: [qcKeys.all], success: 'Criteria removed', onSuccess: () => setDrop(null) })
  const manage = can('site.signoff')
  return (
    <div>
      <p className="mb-3 text-[13px] text-muted-foreground">What a grade of concrete must reach, at each age, on one project - as the approved specification says. A result with nothing here to read against is sent for engineering review, never passed.</p>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <ProjectPicker id="cq-job" value={job} onChange={setJob} className="w-72" />
        {manage && <Button size="sm" className="ml-auto" disabled={!job} onClick={() => setEdit('new')}><Plus /> Add criteria</Button>}
      </div>
      {q.isPending ? <Skeleton className="h-24 w-full" /> : !job ? <p className="text-[13px] text-muted-foreground">Choose a project.</p> : !q.data?.length ? <p className="text-[13px] text-muted-foreground">No criteria set for this project yet.</p> : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table aria-label="Acceptance criteria" className="w-full min-w-[34rem] text-[13.5px]">
            <thead className="bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Grade</th><th className="px-3">Age</th><th className="px-3">Average at least</th><th className="px-3">Single cube at least</th><th className="px-3">Source</th><th className="px-3">Approved</th><th /></tr></thead>
            <tbody>
              {q.data.map((c) => (
                <tr key={c.id} className="border-t border-border">
                  <td className="px-3 py-2 font-medium">{c.grade}</td><td className="px-3">{c.age_days} d</td><td className="px-3">{c.min_mean} MPa</td><td className="px-3">{c.min_single ? `${c.min_single} MPa` : '-'}</td>
                  <td className="px-3">{c.standard}</td><td className="px-3 text-xs text-muted-foreground">{c.approved_by}<br />{formatDate(c.approved_on)}</td>
                  <td className="px-3 text-right">{manage && <><Button size="sm" variant="outline" onClick={() => setEdit(c)}>Edit</Button> <Button size="sm" variant="ghost" aria-label={`Remove ${c.grade} at ${c.age_days} days`} onClick={() => setDrop(c)}><Trash2 /></Button></>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!manage && <p className="mt-3 text-xs text-muted-foreground">Acceptance criteria are kept by those who sign off site work.</p>}
      {edit && <CriteriaForm key={edit === 'new' ? 'new' : edit.id} criteria={edit === 'new' ? null : edit} job={job} onClose={() => setEdit(null)} />}
      <ConfirmDialog open={!!drop} onOpenChange={(o) => !o && setDrop(null)} title={drop ? `Remove ${drop.grade} at ${drop.age_days} days?` : ''} description="Results already recorded keep what they were read against. New results at this age will go for engineering review." tone="danger" confirmLabel="Remove" loading={remove.isPending} onConfirm={() => { if (drop) remove.mutate(drop) }} />
    </div>
  )
}

function CriteriaForm({ criteria: c, job, onClose }: { criteria: Criteria | null; job: number; onClose: () => void }) {
  const [grade, setGrade] = useState(c?.grade ?? 'M25')
  const [age, setAge] = useState(c?.age_days ?? 28)
  const [mean, setMean] = useState(c?.min_mean ?? 0)
  const [single, setSingle] = useState(c?.min_single ?? 0)
  const [std, setStd] = useState(c?.standard ?? '')
  const [tried, setTried] = useState(false)
  const g = grade.trim().toUpperCase()
  const errors = {
    grade: /^M\d{2,3}$/.test(g) ? '' : 'The grade as it is written: M20, M25, M30...',
    age: age >= 1 && age <= 365 ? '' : 'The age in days, 1 to 365.',
    mean: mean > 0 && mean <= 150 ? '' : 'The strength the average must reach, in MPa.',
    single: single >= 0 && single <= mean ? '' : 'Cannot be above the average required.',
    std: std.trim() ? '' : 'Say where this comes from - the specification clause or the standard.',
  }
  const bad = Object.values(errors).some(Boolean)
  const save = useAction(() => saveCriteria(c?.id ?? null, { job_id: job, grade: g, age_days: age, min_mean: mean, min_single: single, standard: std }), { invalidate: [qcKeys.all], success: 'Criteria saved', onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={c ? `Change ${c.grade} at ${c.age_days} days` : 'Add acceptance criteria'} description="Recorded with your name and today's date as the approval.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Concrete grade" htmlFor="cf-grade" error={tried ? errors.grade : ''}><Input id="cf-grade" value={grade} onChange={(e) => setGrade(e.target.value)} /></Field>
        <Field label="Age at test (days)" htmlFor="cf-age" error={tried ? errors.age : ''}><NumField id="cf-age" value={age} onValue={setAge} /></Field>
        <Field label="Average must reach (MPa)" htmlFor="cf-mean" error={tried ? errors.mean : ''}><NumField id="cf-mean" value={mean} onValue={setMean} /></Field>
        <Field label="No single cube below (MPa)" htmlFor="cf-single" hint="0 if the specification sets no individual limit" error={tried ? errors.single : ''}><NumField id="cf-single" value={single} onValue={setSingle} /></Field>
        <Field label="Source" htmlFor="cf-std" error={tried ? errors.std : ''} className="sm:col-span-2"><Input id="cf-std" value={std} placeholder="IS 456:2000 cl. 16 / Project spec 03300 cl. 4.2" onChange={(e) => setStd(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => (bad ? setTried(true) : save.mutate())}>Save</Button>
      </div>
    </Modal>
  )
}
