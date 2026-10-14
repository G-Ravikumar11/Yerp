import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Field, Input, Modal, Textarea } from '@/components/ui'
import { peopleKeys, saveDepartment, showDepartmentChange, useDepartments, type Department } from '@/api/people'
import { useAction } from '@/lib/mutate'
import { Members } from './DepartmentMembersModal'
import { DEPARTMENT_COLORS, DEPARTMENT_ICONS } from './icons'

export function DepartmentModal({ dept, open, onClose, initialTab = 'details' }: { dept: Department | null; open: boolean; onClose: () => void; initialTab?: 'details' | 'people' }) {
  const [tab, setTab] = useState<'details' | 'people'>(initialTab)
  // Read live so the people list follows each add and removal.
  const live = useDepartments().data?.find((d) => d.id === dept?.id) ?? dept
  return (
    <Modal open={open} onOpenChange={(o) => { if (!o) { setTab('details'); onClose() } }} size={dept ? 'lg' : undefined} title={dept ? `Edit ${dept.name}` : 'New department'} description={dept ? undefined : 'Departments you create here are the ones employees belong to, and the ones offered on work orders. Staff see their own department when they sign in.'}>
      {open && dept && (
        <div role="tablist" aria-label="Section" className="mb-4 flex gap-2">
          {(['details', 'people'] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={'rounded-lg border px-3 py-1.5 text-sm font-medium ' + (tab === t ? 'border-[var(--primary)] bg-[var(--primary)]/15' : 'border-border text-muted-foreground hover:text-foreground')}>
              {t === 'details' ? 'Details' : `People (${live?.employee_count ?? 0})`}
            </button>
          ))}
        </div>
      )}
      {open && (dept && tab === 'people' && live ? <Members key={dept.id} dept={live} onClose={onClose} /> : <Form key={dept?.id ?? 'new'} dept={dept} onClose={onClose} />)}
    </Modal>
  )
}

function Form({ dept, onClose }: { dept: Department | null; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState(dept?.name ?? '')
  const [description, setDescription] = useState(dept?.description ?? '')
  const [color, setColor] = useState(dept?.color ?? DEPARTMENT_COLORS[0])
  const [icon, setIcon] = useState(dept?.icon ?? 'building')
  const depts = useDepartments()
  // Caught here so the dialog can say so; it is the one refusal an edit commonly meets.
  const taken = (depts.data ?? []).some((d) => d.id !== dept?.id && d.name.trim().toLowerCase() === name.trim().toLowerCase())
  const save = useAction(() => saveDepartment(dept?.id ?? null, { name: name.trim(), description, color, icon }), {
    success: () => (dept ? 'Department updated' : 'Department created'),
    onSuccess: (saved) => { showDepartmentChange(qc, { saved }); if (!dept) onClose() },
    onError: () => { if (dept) void qc.invalidateQueries({ queryKey: peopleKeys.all }) },
  })
  // An edit shows at once and is saved behind it. A new department waits: its id comes from the server.
  const submit = () => {
    if (dept) {
      showDepartmentChange(qc, { saved: { ...dept, name: name.trim(), description, color, icon } }, { refresh: false })
      onClose()
    }
    save.mutate()
  }
  return (
    <div>
      <div className="grid gap-4">
        <Field label="Name" htmlFor="dp-name"><Input id="dp-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Civil, Accounts, Stores..." autoFocus /></Field>
        <Field label="What it does" htmlFor="dp-desc"><Textarea id="dp-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        <div>
          <p className="mb-1.5 text-sm font-medium">Colour</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Colour">
            {DEPARTMENT_COLORS.map((c) => <button key={c} type="button" role="radio" aria-checked={color === c} aria-label={c} onClick={() => setColor(c)} style={{ background: c }} className={`size-8 rounded-full ring-offset-2 ring-offset-background transition ${color === c ? 'ring-2 ring-foreground' : ''}`} />)}
          </div>
        </div>
        <div>
          <p className="mb-1.5 text-sm font-medium">Icon</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Icon">
            {Object.entries(DEPARTMENT_ICONS).map(([k, Icon]) => <button key={k} type="button" role="radio" aria-checked={icon === k} aria-label={k} onClick={() => setIcon(k)} className={`grid size-9 place-items-center rounded-lg border ${icon === k ? 'border-primary bg-primary-soft text-primary' : 'border-border text-muted-foreground hover:text-foreground'}`}><Icon className="size-4" /></button>)}
          </div>
        </div>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {(taken || save.error) && <p role="alert" className="mr-auto text-[13px] text-danger">{taken ? `A department called '${name.trim()}' already exists` : save.error?.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!name.trim() || taken} onClick={submit}>Save department</Button>
      </div>
    </div>
  )
}
