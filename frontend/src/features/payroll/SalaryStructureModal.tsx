import { useState } from 'react'
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select, Skeleton } from '@/components/ui'
import { addComponent, payKeys, removeComponent, reorderComponents, saveComponent, useSalaryStructure, type ComponentInput, type SalaryComponent } from '@/api/payroll'
import { useAction } from '@/lib/mutate'

const COUNTS: Record<string, { value: string; label: string }[]> = {
  earning: [{ value: 'basic', label: 'Basic pay' }, { value: 'allowance', label: 'An allowance' }],
  deduction: [{ value: 'pf', label: 'PF' }, { value: 'esi', label: 'ESI' }, { value: 'other', label: 'Another deduction' }],
}

const blank = (): ComponentInput => ({ name: '', kind: 'earning', basis: 'percent', percent: 0, counts_as: 'allowance', is_active: true })

/** What a month's pay is made of: the components and how each is worked out. HR keeps it; payslips are made from it. */
export function SalaryStructureModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="xl" title="Salary structure"
      description="Each component is a share of the employee's monthly salary, or is typed by hand on each payslip. A payslip takes these when it is made; changing them later does not touch payslips already made.">
      {open && <Body />}
    </Modal>
  )
}

function Body() {
  const q = useSalaryStructure()
  const [editing, setEditing] = useState<{ id: number | null; v: ComponentInput } | null>(null)
  const [removing, setRemoving] = useState<SalaryComponent | null>(null)
  const refresh = { invalidate: [payKeys.all] }
  const rows = q.data?.components ?? []
  const save = useAction((x: { id: number | null; v: ComponentInput }) => (x.id ? saveComponent(x.id, x.v) : addComponent(x.v)), { ...refresh, success: (r) => r.message || 'Saved', onSuccess: () => setEditing(null) })
  const toggle = useAction((c: SalaryComponent) => saveComponent(c.id, { is_active: !c.is_active }), refresh)
  const remove = useAction((c: SalaryComponent) => removeComponent(c.id), { ...refresh, success: (r) => r.message || 'Removed', onSuccess: () => setRemoving(null) })
  const move = useAction((x: { from: number; by: number }) => {
    const ids = rows.map((c) => c.id)
    const [id] = ids.splice(x.from, 1)
    ids.splice(x.from + x.by, 0, id!)
    return reorderComponents(ids)
  }, refresh)
  const v = editing?.v
  const set = (patch: ComponentInput) => setEditing((e) => (e ? { ...e, v: { ...e.v, ...patch } } : e))
  const how = (c: SalaryComponent) => (c.basis === 'percent' ? `${c.percent}% of the monthly salary` : 'Typed on each payslip')

  if (q.isPending) return <Skeleton className="h-64 w-full" />
  return (
    <div>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-[13px] text-muted-foreground">
            <tr><th className="px-3 py-2 font-medium">Component</th><th className="px-3 py-2 font-medium">Is</th><th className="px-3 py-2 font-medium">Worked out as</th><th className="px-3 py-2 font-medium">On</th><th className="px-3 py-2 text-right font-medium">Change</th></tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">No components. Payslips are then made from the salary alone. Add one to start again.</td></tr>}
            {rows.map((c, i) => (
              <tr key={c.id} className={c.is_active ? '' : 'text-muted-foreground'}>
                <td className="px-3 py-2 font-medium">{c.name}</td>
                <td className="px-3 py-2">{c.kind === 'earning' ? 'Earning' : 'Deduction'}</td>
                <td className="px-3 py-2">{how(c)}</td>
                <td className="px-3 py-2"><button type="button" role="switch" aria-checked={c.is_active} aria-label={`${c.name} on payslips`} onClick={() => toggle.mutate(c)}><Badge tone={c.is_active ? 'success' : 'neutral'} dot>{c.is_active ? 'On' : 'Off'}</Badge></button></td>
                <td className="px-3 py-2">
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="ghost" aria-label={`Move ${c.name} up`} disabled={i === 0 || move.isPending} onClick={() => move.mutate({ from: i, by: -1 })}><ArrowUp /></Button>
                    <Button size="sm" variant="ghost" aria-label={`Move ${c.name} down`} disabled={i === rows.length - 1 || move.isPending} onClick={() => move.mutate({ from: i, by: 1 })}><ArrowDown /></Button>
                    <Button size="sm" variant="ghost" aria-label={`Edit ${c.name}`} onClick={() => setEditing({ id: c.id, v: { name: c.name, kind: c.kind, basis: c.basis, percent: c.percent, counts_as: c.counts_as, is_active: c.is_active } })}><Pencil /></Button>
                    <Button size="sm" variant="ghost" className="text-danger" aria-label={`Remove ${c.name}`} onClick={() => setRemoving(c)}><Trash2 /></Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!editing && <div className="mt-4"><Button variant="outline" onClick={() => setEditing({ id: null, v: blank() })}><Plus /> Add a component</Button></div>}
      {editing && v && (
        <div className="mt-4 rounded-lg border border-border p-4">
          <h3 className="mb-3 text-sm font-semibold">{editing.id ? `Change ${v.name || 'component'}` : 'Add a component'}</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Name" htmlFor="sc-name"><Input id="sc-name" value={v.name ?? ''} onChange={(e) => set({ name: e.target.value })} autoFocus /></Field>
            <Field label="Is" htmlFor="sc-kind"><Select id="sc-kind" value={v.kind ?? 'earning'} onChange={(e) => set({ kind: e.target.value as 'earning' | 'deduction', counts_as: e.target.value === 'earning' ? 'allowance' : 'other' })} options={[{ value: 'earning', label: 'An earning' }, { value: 'deduction', label: 'A deduction' }]} /></Field>
            <Field label="Worked out as" htmlFor="sc-basis"><Select id="sc-basis" value={v.basis ?? 'percent'} onChange={(e) => set({ basis: e.target.value as 'percent' | 'manual' })} options={[{ value: 'percent', label: 'A percentage of the monthly salary' }, { value: 'manual', label: 'Typed on each payslip' }]} /></Field>
            {v.basis === 'percent' && <Field label="Percentage" htmlFor="sc-pct" hint="0 to 100"><NumField id="sc-pct" value={v.percent ?? 0} onValue={(n) => set({ percent: n })} /></Field>}
            <Field label="Counts as" htmlFor="sc-counts" hint="Which total on the payslip it goes into."><Select id="sc-counts" value={v.counts_as ?? ''} onChange={(e) => set({ counts_as: e.target.value })} options={COUNTS[v.kind ?? 'earning']!} /></Field>
          </div>
          <div className="mt-4 flex items-center justify-end gap-2">
            {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
            <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
            <Button loading={save.isPending} disabled={!(v.name ?? '').trim()} onClick={() => save.mutate(editing)}>{editing.id ? 'Save' : 'Add it'}</Button>
          </div>
        </div>
      )}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Remove ${removing?.name ?? ''}?`} description="Payslips already made keep it. Only the payslips made from now on leave it out." confirmLabel="Remove it" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing) }} />
    </div>
  )
}
