import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Search, Trash2, Upload } from 'lucide-react'
import { Button, Input, Modal, Skeleton } from '@/components/ui'
import { api, apiUrl, get, put } from '@/lib/api'
import { formatQty } from '@/lib/format'
import { useAction } from '@/lib/mutate'
import { ApiError } from '@/lib/api'

/** One material of a work item's norm: how much one unit of the work uses, and the wastage added on top. */
export interface Norm { material_id: number; item_code: string; item_name: string; hsn: string; unit: string; qty_per_unit: number; wastage_pct: number; remarks: string; is_active: boolean }
interface Norms { item_id: number; item_code: string; item_name: string; unit: string; is_work: boolean; norms: Norm[] }
interface Material { id: number; item_code: string; item_name: string; units_of_measure: string }

const normsKey = (id: number) => ['item-norms', id] as const
export const NORMS_SHEET_URL = '/api/items/norms.xlsx'

/** A store material found by code or name in the Item Master. */
function MaterialSearch({ onPick, label }: { onPick: (m: Material) => void; label: string }) {
  const [text, setText] = useState('')
  const [typed, setTyped] = useState('')
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { const t = setTimeout(() => setTyped(text.trim()), 200); return () => clearTimeout(t) }, [text])
  useEffect(() => {
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])
  const found = useQuery({
    queryKey: ['item-norm-materials', typed], enabled: open,
    queryFn: () => get<{ items: Material[] }>(`/api/items?kind=RM&status=active&page_size=20&sort=name&q=${encodeURIComponent(typed)}`),
  })
  return (
    <div ref={box} className="relative">
      <Input aria-label={label} leading={<Search />} value={text} placeholder="Search material code or name" autoComplete="off"
        onFocus={() => setOpen(true)} onChange={(e) => { setText(e.target.value); setOpen(true) }} />
      {open && (
        <ul role="listbox" className="absolute top-full z-30 mt-1 max-h-56 w-full overflow-auto rounded-md border border-input bg-popover py-1 text-sm shadow-md">
          {(found.data?.items ?? []).map((m) => (
            <li key={m.id} role="option" aria-selected={false}>
              <button type="button" className="flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left hover:bg-accent"
                onClick={() => { onPick(m); setOpen(false); setText('') }}>
                <span className="min-w-0 truncate"><span className="font-mono text-xs text-muted-foreground">{m.item_code}</span> {m.item_name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{m.units_of_measure}</span>
              </button>
            </li>
          ))}
          {!found.isFetching && !(found.data?.items ?? []).length && <li className="px-3 py-2 text-muted-foreground">No material found</li>}
        </ul>
      )}
    </div>
  )
}

interface Row { material_id: number; item_code: string; item_name: string; unit: string; qty: string; waste: string; remarks: string }

/**
 * A work item's material norms, in its detail window: what one unit of the work uses of each store material, with the wastage
 * allowed. The Item sheet fills a BOQ line's materials from them. Set here, from the norms Excel, or saved from an Item sheet line.
 */
export function NormsSection({ itemId, unit, manage }: { itemId: number; unit: string; manage: boolean }) {
  const qc = useQueryClient()
  const data = useQuery({ queryKey: normsKey(itemId), queryFn: () => get<Norms>(`/api/items/${itemId}/norms`) })
  const [rows, setRows] = useState<Row[] | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const save = useAction(() => put<Norms>(`/api/items/${itemId}/norms`, {
    rows: (rows ?? []).map((r) => ({ material_id: r.material_id, qty_per_unit: r.qty === '' ? null : Number(r.qty), wastage_pct: r.waste === '' ? 0 : Number(r.waste), remarks: r.remarks })),
  }), {
    success: 'Norms saved. The Item sheet fills lines of this work from them.',
    onSuccess: (r) => { qc.setQueryData(normsKey(itemId), r); setRows(null); setProblems([]) },
    onError: (e) => setProblems(e instanceof ApiError ? e.detail.split('\n').slice(1) : []),
  })
  const edit = () => setRows((data.data?.norms ?? []).map((n) => ({
    material_id: n.material_id, item_code: n.item_code, item_name: n.item_name, unit: n.unit, qty: String(n.qty_per_unit), waste: n.wastage_pct ? String(n.wastage_pct) : '', remarks: n.remarks,
  })))
  const set = (i: number, patch: Partial<Row>) => setRows((rs) => (rs ?? []).map((r, n) => (n === i ? { ...r, ...patch } : r)))
  const per = unit || 'unit'

  return (
    <section aria-labelledby="d-norms">
      <h3 id="d-norms" className="mb-2 flex items-center justify-between border-b pb-1 text-sm font-semibold">
        <span>Materials per {per} (norms)</span>
        {manage && !rows && data.data && <Button size="sm" variant="ghost" onClick={edit}><Pencil /> Edit norms</Button>}
      </h3>
      {data.isPending && <Skeleton className="h-10 w-full" />}
      {data.data && !rows && (data.data.norms.length ? (
        <table className="w-full text-sm" aria-label="Norms">
          <thead className="text-xs text-muted-foreground"><tr className="border-b"><th className="py-1 text-left font-medium">Material</th><th className="py-1 text-right font-medium">Per 1 {per}</th><th className="py-1 text-right font-medium">Wastage</th></tr></thead>
          <tbody>
            {data.data.norms.map((n) => (
              <tr key={n.material_id} className="border-b last:border-0">
                <td className="py-1.5"><span className="font-mono text-xs text-muted-foreground">{n.item_code}</span> {n.item_name}{!n.is_active && <span className="text-warning"> (switched off)</span>}{n.remarks && <span className="text-xs text-muted-foreground"> · {n.remarks}</span>}</td>
                <td className="py-1.5 text-right tabular">{formatQty(n.qty_per_unit)} {n.unit}</td>
                <td className="py-1.5 text-right tabular">{n.wastage_pct ? `${n.wastage_pct}%` : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-sm text-muted-foreground">No norms yet. Say what one {per} of this work uses of each material, and the Item sheet fills BOQ lines of this work for you.</p>
      ))}
      {rows && (
        <div className="space-y-2">
          {problems.length > 0 && <ul role="alert" className="list-disc rounded-md bg-danger-soft py-2 pl-8 pr-3 text-sm text-danger">{problems.map((p, i) => <li key={i}>{p}</li>)}</ul>}
          {rows.map((r, i) => (
            <div key={r.material_id} className="grid items-end gap-2 rounded-md border p-2 sm:grid-cols-[minmax(0,1fr)_7rem_6rem_auto]">
              <div className="text-sm"><span className="font-mono text-xs text-muted-foreground">{r.item_code}</span> {r.item_name}
                <Input aria-label={`Remarks for ${r.item_name}`} className="mt-1 h-8" placeholder="Remarks (optional)" value={r.remarks} onChange={(e) => set(i, { remarks: e.target.value })} />
              </div>
              <label className="text-xs text-muted-foreground">{r.unit} per {per}
                <Input aria-label={`${r.item_name} per ${per}`} inputMode="decimal" value={r.qty} onChange={(e) => set(i, { qty: e.target.value.replace(/[^\d.]/g, '') })} />
              </label>
              <label className="text-xs text-muted-foreground">Wastage %
                <Input aria-label={`Wastage of ${r.item_name}`} inputMode="decimal" value={r.waste} onChange={(e) => set(i, { waste: e.target.value.replace(/[^\d.]/g, '') })} />
              </label>
              <Button variant="ghost" size="icon" aria-label={`Remove ${r.item_name}`} onClick={() => setRows((rs) => (rs ?? []).filter((_, n) => n !== i))}><Trash2 /></Button>
            </div>
          ))}
          <MaterialSearch label="Add a material to the norms" onPick={(m) => setRows((rs) => (rs ?? []).some((r) => r.material_id === m.id) ? rs
            : [...(rs ?? []), { material_id: m.id, item_code: m.item_code, item_name: m.item_name, unit: m.units_of_measure, qty: '', waste: '', remarks: '' }])} />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => { setRows(null); setProblems([]) }}>Cancel</Button>
            <Button onClick={() => save.mutate()} loading={save.isPending}><Plus /> Save norms</Button>
          </div>
        </div>
      )}
    </section>
  )
}

/** Every work item's norms at once: download the sheet (every work item listed), fill it, upload it. All or nothing. */
export function NormsImportModal({ onClose }: { onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const qc = useQueryClient()
  const send = useAction(() => {
    const form = new FormData()
    form.append('file', file as File)
    return api<{ message: string }>('/api/items/norms/upload', { method: 'POST', body: form })
  }, {
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['item-norms'] }); onClose() },
    onError: (e) => setProblems(e instanceof ApiError ? e.detail.split('\n').slice(1) : []),
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Material norms from Excel" size="lg"
      description="One row per material a work item uses: how much ONE unit of the work uses, and the wastage %. The Item sheet fills BOQ lines from these."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={() => send.mutate()} loading={send.isPending} disabled={!file}><Upload /> Upload</Button></>}>
      <div className="space-y-3 text-sm">
        <p>1. <a className="font-medium text-primary hover:underline" href={apiUrl(NORMS_SHEET_URL)}>Download the norms sheet</a>. Every work item is listed, with its norms if it has any.</p>
        <p>2. Fill a row for each material: its code, the quantity per 1 work unit, and the wastage %. Add rows for a work item with more materials.</p>
        <p>3. Upload it. A work item in the file gets exactly the materials listed for it; nothing is saved if any row is wrong.</p>
        <input type="file" accept=".xlsx" aria-label="The filled norms sheet" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setProblems([]) }} />
        {problems.length > 0 && <ul role="alert" className="max-h-60 list-disc overflow-auto rounded-md bg-danger-soft py-2 pl-8 pr-3 text-danger">{problems.map((p, i) => <li key={i}>{p}</li>)}</ul>}
      </div>
    </Modal>
  )
}
