import { useState } from 'react'
import { Pencil, Trash2 } from 'lucide-react'
import { Button, ConfirmDialog, Field, Input, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useProjects, projectLabel } from '@/api/projects'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storeDelete, storePerm, storePost, storePut, type StoreItemOption } from '@/api/store'
import { ItemPicker } from '../shared'
import { num, reportKeys, useBoqPicks, useNorms, type Norm } from './api'

const blank = { boq_item_id: 0, item: null as StoreItemOption | null, qty_per_unit: '', wastage_pct: '', notes: '' }

/** Material norms: how much of an item one unit of a BOQ item should consume, with an allowance for wastage. The norms report sets them against actual issues. */
export default function NormsPage() {
  const { can } = useSession()
  const projects = useProjects()
  const [project, setProject] = useState(0)
  const norms = useNorms(project)
  const boq = useBoqPicks(project)
  const [f, setF] = useState(blank)
  const [editing, setEditing] = useState<Norm | null>(null)
  const [removing, setRemoving] = useState<Norm | null>(null)
  const canEdit = can(storePerm('reports', 'create'))
  const refresh = [[...reportKeys.all, 'norms']]
  const save = useAction(
    () => {
      const body = { boq_item_id: f.boq_item_id, item_id: f.item?.id, qty_per_unit: f.qty_per_unit, wastage_pct: f.wastage_pct || '0', notes: f.notes }
      return editing ? storePut<Norm>('reports', `/norms/${editing.id}`, body) : storePost<Norm>('reports', '/norms', body)
    },
    { invalidate: refresh, success: editing ? 'Norm saved' : 'Norm added', onSuccess: () => { setF(blank); setEditing(null) } },
  )
  const drop = useAction((n: Norm) => storeDelete<{ message: string }>('reports', `/norms/${n.id}`), { invalidate: refresh, success: 'Norm removed' })
  const columns: TableColumn<Norm>[] = [
    { id: 'boq', header: 'BOQ item', cell: (n) => <div><div className="font-medium">{n.boq_item}</div><div className="text-xs text-muted-foreground">{num(n.boq_qty)} {n.boq_uom}</div></div> },
    { id: 'item', header: 'Item', cell: (n) => <div><div className="font-medium">{n.item_name}</div><div className="font-mono text-xs text-muted-foreground">{n.item_code}</div></div> },
    { id: 'per', header: 'Per unit', align: 'right', width: '9rem', cell: (n) => `${num(n.qty_per_unit)} ${n.base_uom}` },
    { id: 'was', header: 'Wastage', align: 'right', width: '6rem', hideBelow: 'sm', cell: (n) => `${num(n.wastage_pct)}%` },
    { id: 'need', header: 'Should use', align: 'right', width: '9rem', cell: (n) => `${num(n.theoretical_qty)} ${n.base_uom}` },
    ...(canEdit ? ([{
      id: 'act', header: '', width: '7rem', cell: (n) => (
        <span className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" aria-label={`Edit the norm for ${n.item_name}`} onClick={() => { setEditing(n); setF({ boq_item_id: n.boq_item_id, item: { id: n.item_id, code: n.item_code, name: n.item_name, base_uom: n.base_uom, uoms: [], category: null }, qty_per_unit: String(Number(n.qty_per_unit)), wastage_pct: Number(n.wastage_pct) ? String(Number(n.wastage_pct)) : '', notes: n.notes }) }}><Pencil /></Button>
          <Button size="sm" variant="ghost" aria-label={`Remove the norm for ${n.item_name}`} onClick={() => setRemoving(n)}><Trash2 /></Button>
        </span>
      ),
    }] as TableColumn<Norm>[]) : []),
  ]
  return (
    <div>
      <Field label="Project" htmlFor="nm-proj" className="mb-4 w-64"><Select id="nm-proj" value={project || ''} placeholder="Choose a project" onChange={(e) => { setProject(Number(e.target.value) || 0); setF(blank); setEditing(null) }} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
      {!project ? <p className="text-sm text-muted-foreground">Choose a project to see and set the norms of its BOQ items.</p> : (
        <>
          <DataTable label="Material norms" rows={norms.data ?? []} loading={norms.isPending} columns={columns} rowKey={(n) => n.id} empty="No norms set for this project yet." />
          {canEdit && (
            <section className="mt-6" aria-labelledby="nm-form">
              <h3 id="nm-form" className="mb-2 border-b pb-1 text-sm font-semibold">{editing ? 'Change the norm' : 'Add a norm'}</h3>
              <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1.4fr)_9rem_8rem_auto]" onSubmit={(e) => { e.preventDefault(); if (f.boq_item_id && f.item && f.qty_per_unit) save.mutate() }}>
                <Field label="BOQ item" htmlFor="nm-boq"><Select id="nm-boq" value={f.boq_item_id || ''} placeholder="Choose" onChange={(e) => setF({ ...f, boq_item_id: Number(e.target.value) || 0 })} options={(boq.data ?? []).map((b) => ({ value: b.id, label: `${b.item_no} ${b.description}`.slice(0, 70) }))} /></Field>
                <Field label="Item" htmlFor="nm-item"><ItemPicker id="nm-item" value={f.item} onChange={(item) => setF({ ...f, item })} /></Field>
                <Field label={`Per unit${f.item ? ` (${f.item.base_uom})` : ''}`} htmlFor="nm-qty" hint="Of the item, for 1 unit of the BOQ item."><Input id="nm-qty" inputMode="decimal" className="text-right" value={f.qty_per_unit} onChange={(e) => setF({ ...f, qty_per_unit: e.target.value })} /></Field>
                <Field label="Wastage %" htmlFor="nm-was"><Input id="nm-was" inputMode="decimal" className="text-right" placeholder="0" value={f.wastage_pct} onChange={(e) => setF({ ...f, wastage_pct: e.target.value })} /></Field>
                <div className="flex items-end gap-2">
                  <Button type="submit" loading={save.isPending} disabled={!f.boq_item_id || !f.item || !f.qty_per_unit}>{editing ? 'Save' : 'Add'}</Button>
                  {editing && <Button type="button" variant="ghost" onClick={() => { setEditing(null); setF(blank) }}>Cancel</Button>}
                </div>
                <Field label="Notes" htmlFor="nm-notes" className="sm:col-span-2 lg:col-span-5"><Input id="nm-notes" value={f.notes} maxLength={200} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
              </form>
            </section>
          )}
        </>
      )}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title="Remove this norm?" description="The norms report will no longer compare this item for that BOQ item." confirmLabel="Remove" tone="danger" onConfirm={() => { if (removing) drop.mutate(removing); setRemoving(null) }} />
    </div>
  )
}
