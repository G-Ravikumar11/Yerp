import { useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Copy, Download, Pencil, Search, Trash2, Upload, Wand2 } from 'lucide-react'
import { Button, ConfirmDialog, Field, Input, Select } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useProjects, projectLabel } from '@/api/projects'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storeDelete, storePerm, storePost, storePut, type StoreItemOption } from '@/api/store'
import { ItemPicker } from '../shared'
import { dmy, normTemplateHref, num, reportKeys, useBoqPicks, useNorms, type Norm } from './api'
import { NormCopyDialog } from './NormCopy'
import { NormImportDialog } from './NormImport'
import { NormFromWorkDialog } from './NormFromWork'

const blank = { boq_item_id: 0, item: null as StoreItemOption | null, qty_per_unit: '', wastage_pct: '', notes: '' }
const PAGE = 25

/** Material norms: how much of an item one unit of a BOQ item should consume, with an allowance for wastage. The norms report and the
 * wastage loss set them against what was issued. Typed one at a time here, imported from a sheet, or copied from another project. */
export default function NormsPage() {
  const { can } = useSession()
  const projects = useProjects()
  const [project, setProject] = useState(0)
  const norms = useNorms(project)
  const boq = useBoqPicks(project)
  const [f, setF] = useState(blank)
  const [editing, setEditing] = useState<Norm | null>(null)
  const [removing, setRemoving] = useState<Norm | null>(null)
  const [dialog, setDialog] = useState<'import' | 'copy' | 'work' | null>(null)
  const [search, setSearch] = useState('')
  const [material, setMaterial] = useState(0)
  const [page, setPage] = useState(0)
  const canEdit = can(storePerm('reports', 'create'))
  // A norm's wastage % is what Budgeting costs the material at, so the budget is read again whenever a norm changes.
  const refresh = [[...reportKeys.all, 'norms'], ['costs', 'wastage'], ['budgeting']]
  const current = (projects.data ?? []).find((p) => p.id === project)
  const label = current ? projectLabel(current) : ''

  const save = useAction(
    () => {
      const body = { boq_item_id: f.boq_item_id, item_id: f.item?.id, qty_per_unit: f.qty_per_unit, wastage_pct: f.wastage_pct || '0', notes: f.notes }
      return editing ? storePut<Norm>('reports', `/norms/${editing.id}`, body) : storePost<Norm>('reports', '/norms', body)
    },
    { invalidate: refresh, success: editing ? 'Norm saved' : 'Norm added', onSuccess: () => { setF(blank); setEditing(null) } },
  )
  const drop = useAction((n: Norm) => storeDelete<{ message: string }>('reports', `/norms/${n.id}`), { invalidate: refresh, success: 'Norm removed' })

  const all = useMemo(() => norms.data ?? [], [norms.data])
  const materials = useMemo(() => {
    const seen = new Map<number, string>()
    for (const n of all) seen.set(n.item_id, `${n.item_name} (${n.item_code})`)
    return [...seen].sort((a, b) => a[1].localeCompare(b[1])).map(([value, l]) => ({ value, label: l }))
  }, [all])
  const shown = useMemo(() => {
    const term = search.trim().toLowerCase()
    return all.filter((n) => (!material || n.item_id === material) && (!term || n.boq_item.toLowerCase().includes(term)))
  }, [all, search, material])
  const pages = Math.max(1, Math.ceil(shown.length / PAGE))
  const at = Math.min(page, pages - 1)                                     // a narrower search never leaves you past the last page
  const onPage = shown.slice(at * PAGE, at * PAGE + PAGE)

  const columns: TableColumn<Norm>[] = [
    { id: 'boq', header: 'BOQ item', sort: (n) => n.boq_item, cell: (n) => <div><div className="font-medium">{n.boq_item}</div><div className="text-xs text-muted-foreground">{num(n.boq_qty)} {n.boq_uom}</div></div> },
    { id: 'item', header: 'Material', sort: (n) => n.item_name, cell: (n) => <div><div className="font-medium">{n.item_name}</div><div className="font-mono text-xs text-muted-foreground">{n.item_code}</div></div> },
    { id: 'per', header: 'Qty per unit', align: 'right', width: '9rem', sort: (n) => Number(n.qty_per_unit), cell: (n) => `${num(n.qty_per_unit)} ${n.base_uom}` },
    { id: 'was', header: 'Wastage %', align: 'right', width: '6.5rem', sort: (n) => Number(n.wastage_pct), cell: (n) => `${num(n.wastage_pct)}%` },
    { id: 'need', header: 'Should use', align: 'right', width: '9rem', hideBelow: 'md', cell: (n) => `${num(n.theoretical_qty)} ${n.base_uom}` },
    { id: 'upd', header: 'Last updated', width: '9rem', hideBelow: 'lg', sort: (n) => n.updated_at, cell: (n) => <div className="text-xs"><div>{n.updated_at ? dmy(n.updated_at) : '-'}</div>{n.updated_by && <div className="text-muted-foreground">{n.updated_by}</div>}</div> },
    ...(canEdit ? ([{
      id: 'act', header: <span className="sr-only">Actions</span>, width: '7rem', cell: (n) => (
        <span className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" aria-label={`Edit the norm for ${n.item_name}`} onClick={() => { setEditing(n); setF({ boq_item_id: n.boq_item_id, item: { id: n.item_id, code: n.item_code, name: n.item_name, base_uom: n.base_uom, uoms: [], category: null }, qty_per_unit: String(Number(n.qty_per_unit)), wastage_pct: Number(n.wastage_pct) ? String(Number(n.wastage_pct)) : '', notes: n.notes }); document.getElementById('nm-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }}><Pencil /></Button>
          <Button size="sm" variant="ghost" aria-label={`Remove the norm for ${n.item_name}`} onClick={() => setRemoving(n)}><Trash2 /></Button>
        </span>
      ),
    }] as TableColumn<Norm>[]) : []),
  ]

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <h2 className="text-base font-semibold">Material Norms</h2>
            <p className="text-xs text-muted-foreground">{label ? `Project: ${label}` : 'No project chosen'}</p>
          </div>
          <Field label="Project" htmlFor="nm-proj" className="w-64"><Select id="nm-proj" value={project || ''} placeholder={projects.isPending ? 'Loading projects...' : 'Choose a project'} onChange={(e) => { setProject(Number(e.target.value) || 0); setF(blank); setEditing(null); setSearch(''); setMaterial(0); setPage(0) }} options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        </div>
        <div className="flex flex-wrap gap-2">
          {canEdit && <Button variant="outline" disabled={!project} onClick={() => setDialog('import')}><Upload /> Import Excel</Button>}
          {project ? <Button variant="outline" asChild><a href={normTemplateHref(project)} download><Download /> Download template</a></Button> : <Button variant="outline" disabled><Download /> Download template</Button>}
          {canEdit && <Button variant="outline" disabled={!project} onClick={() => setDialog('copy')}><Copy /> Copy norms from another project</Button>}
          {canEdit && <Button variant="outline" disabled={!project} onClick={() => setDialog('work')}><Wand2 /> From the work items' norms</Button>}
        </div>
      </div>

      {!project ? <p className="text-sm text-muted-foreground">Choose a project to see and set the norms of its BOQ items.</p> : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <div className="w-full sm:w-72"><Input aria-label="Search BOQ items" placeholder="Search BOQ items" leading={<Search />} value={search} onChange={(e) => { setSearch(e.target.value); setPage(0) }} /></div>
            <div className="w-full sm:w-64"><Select aria-label="Filter by material" value={material || ''} placeholder="All materials" onChange={(e) => { setMaterial(Number(e.target.value) || 0); setPage(0) }} options={materials} /></div>
            <span className="text-xs text-muted-foreground">{shown.length} of {all.length} norm{all.length === 1 ? '' : 's'}</span>
          </div>
          {norms.isError ? (
            <p className="rounded-lg border border-danger/30 bg-danger-soft p-3 text-sm text-danger" role="alert">The norms could not be loaded: {(norms.error as Error).message} <Button size="sm" variant="ghost" onClick={() => norms.refetch()}>Try again</Button></p>
          ) : (
            <DataTable label="Material norms" rows={onPage} loading={norms.isPending} columns={columns} rowKey={(n) => n.id}
              empty={all.length ? 'No norm matches that search.' : 'No norms set for this project yet. Add one below, import a sheet, or copy them from another project.'} />
          )}
          {pages > 1 && (
            <nav aria-label="Pages" className="mt-2 flex items-center justify-end gap-2 text-sm">
              <Button size="sm" variant="ghost" disabled={at === 0} onClick={() => setPage(at - 1)} aria-label="Previous page"><ChevronLeft /></Button>
              <span className="tabular-nums text-muted-foreground">Page {at + 1} of {pages}</span>
              <Button size="sm" variant="ghost" disabled={at >= pages - 1} onClick={() => setPage(at + 1)} aria-label="Next page"><ChevronRight /></Button>
            </nav>
          )}
          {canEdit && (
            <section className="mt-6" aria-labelledby="nm-form">
              <h3 id="nm-form" className="mb-2 border-b pb-1 text-sm font-semibold">{editing ? 'Change the norm' : 'Add a norm'}</h3>
              <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1.4fr)_9rem_8rem_auto]" onSubmit={(e) => { e.preventDefault(); if (f.boq_item_id && f.item && f.qty_per_unit) save.mutate() }}>
                <Field label="BOQ item" htmlFor="nm-boq"><Select id="nm-boq" value={f.boq_item_id || ''} placeholder={boq.isPending ? 'Loading...' : 'Choose'} onChange={(e) => setF({ ...f, boq_item_id: Number(e.target.value) || 0 })} options={(boq.data ?? []).map((b) => ({ value: b.id, label: `${b.item_no} ${b.description}`.slice(0, 70) }))} /></Field>
                <Field label="Material" htmlFor="nm-item"><ItemPicker id="nm-item" value={f.item} onChange={(item) => setF({ ...f, item })} /></Field>
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
      {dialog === 'import' && project > 0 && <NormImportDialog projectId={project} projectLabel={label} onClose={() => setDialog(null)} />}
      {dialog === 'copy' && project > 0 && <NormCopyDialog projectId={project} projectLabel={label} onClose={() => setDialog(null)} />}
      {dialog === 'work' && project > 0 && <NormFromWorkDialog projectId={project} projectLabel={label} onClose={() => setDialog(null)} />}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title="Remove this norm?" description={removing ? `${removing.item_name} for ${removing.boq_item}. The norms report and the wastage loss will no longer compare this material for that BOQ item.` : ''} confirmLabel="Remove" tone="danger" loading={drop.isPending} onConfirm={() => { if (removing) drop.mutate(removing); setRemoving(null) }} />
    </div>
  )
}
