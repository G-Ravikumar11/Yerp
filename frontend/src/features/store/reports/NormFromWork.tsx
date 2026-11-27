import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Wand2 } from 'lucide-react'
import { storeGet, storePost } from '@/api/store'
import { Badge, Button, ConfirmDialog, Field, Modal, Select } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'
import { num, qs, reportKeys, type CopyMode } from './api'

type Status = 'insert' | 'update' | 'unchanged' | 'skip' | 'unit' | 'no_material'
export interface FromWorkRow {
  boq_item_id: number; boq_item: string; boq_uom: string; work_item_id: number; work_code: string; work_name: string; work_uom: string
  item_id: number; item_code: string; item_name: string; base_uom: string; qty_per_unit: string; wastage_pct: string; status: Status
  current: { qty_per_unit: string; wastage_pct: string } | null
}
interface Preview {
  project: { id: number; label: string }
  rows: FromWorkRow[]
  summary: { total: number; insert: number; update: number; unchanged: number; skip: number; unit: number; no_material: number; no_work: number; no_norms: number }
}
interface Result { inserted: number; updated: number; unchanged: number; skipped_existing: number; message: string }

const STATUS: Record<Status, { label: string; tone: 'success' | 'info' | 'neutral' | 'warning' | 'danger' }> = {
  insert: { label: 'Will be added', tone: 'success' },
  update: { label: 'Will replace', tone: 'info' },
  unchanged: { label: 'Same as here', tone: 'neutral' },
  skip: { label: 'Already set here - kept', tone: 'warning' },
  unit: { label: 'Units differ - skipped', tone: 'danger' },
  no_material: { label: 'Material not in master - skipped', tone: 'danger' },
}

/** This project's norms from the work items its BOQ items are (Item Master > a work item > its norms): see what each would become, then bring them in. */
export function NormFromWorkDialog({ projectId, projectLabel, onClose }: { projectId: number; projectLabel: string; onClose: () => void }) {
  const [mode, setMode] = useState<CopyMode>('add')
  const [confirming, setConfirming] = useState(false)
  const [result, setResult] = useState<Result | null>(null)
  const preview = useQuery({
    queryKey: ['store', 'reports', 'norm-from-work', projectId, mode], gcTime: 0,
    queryFn: () => storeGet<Preview>('reports', `/norms/from-work/preview${qs({ project_id: projectId, mode })}`),
  })
  const save = useAction(() => storePost<Result>('reports', '/norms/from-work', { project_id: projectId, mode }), {
    invalidate: [[...reportKeys.all, 'norms'], [...reportKeys.all, 'norm-sources'], ['costs', 'wastage'], ['item-sheet']],
    onSuccess: (r) => { setResult(r); setConfirming(false) }, onError: () => setConfirming(false),
  })
  const s = preview.data?.summary
  const rows = preview.data?.rows ?? []
  const taking = (s?.insert ?? 0) + (s?.update ?? 0)
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title="Norms from the work items"
      description={`Into ${projectLabel}. Each BOQ item takes the norms of the work item it is (Item Master), where both count in the same unit.`}
      footer={result ? <Button onClick={onClose}>Done</Button> : (
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => setConfirming(true)} disabled={!taking}><Wand2 /> Bring in {taking} norm{taking === 1 ? '' : 's'}</Button>
        </div>
      )}>
      {result ? (
        <div className="space-y-2 text-sm" role="status">
          <p className="font-medium">{result.message}</p>
          <p className="text-muted-foreground">{result.inserted} added, {result.updated} replaced, {result.unchanged} already the same, {result.skipped_existing} already set here and kept.</p>
        </div>
      ) : (
        <div className="space-y-4">
          <Field label="When a norm is already set here" htmlFor="nw-mode" className="max-w-xs">
            <Select id="nw-mode" value={mode} onChange={(e) => setMode(e.target.value as CopyMode)}
              options={[{ value: 'add', label: 'Add missing norms only' }, { value: 'replace', label: 'Replace matching norms' }]} />
          </Field>
          {preview.isPending ? <p className="text-sm text-muted-foreground" role="status">Reading the work items of this project's BOQ...</p>
            : preview.isError ? <p className="text-sm text-danger" role="alert">{(preview.error as Error).message}</p>
            : s && (
              <>
                <div className="flex flex-wrap gap-2 text-xs">
                  {s.insert > 0 && <Badge tone="success">{s.insert} to add</Badge>}
                  {s.update > 0 && <Badge tone="info">{s.update} to replace</Badge>}
                  {s.skip > 0 && <Badge tone="warning">{s.skip} already set here</Badge>}
                  {s.unit > 0 && <Badge tone="danger">{s.unit} in a different unit</Badge>}
                  {s.no_norms > 0 && <Badge tone="neutral">{s.no_norms} BOQ item{s.no_norms === 1 ? '' : 's'} whose work item has no norms</Badge>}
                  {s.no_work > 0 && <Badge tone="neutral">{s.no_work} BOQ item{s.no_work === 1 ? '' : 's'} with no work item</Badge>}
                </div>
                {!rows.length ? (
                  <p className="text-sm text-muted-foreground">No BOQ item of this project has a work item with norms. Set norms on the work items in the Item Master, or say on the Item sheet which work item each BOQ line is.</p>
                ) : (
                  <div className="max-h-[26rem] overflow-auto rounded-lg border border-border">
                    <table className="w-full min-w-max text-[13px]" aria-label="Norms from the work items">
                      <thead className="sticky top-0 z-10 bg-surface text-left text-xs text-muted-foreground">
                        <tr>
                          <th className="px-2.5 py-2">BOQ item</th><th className="px-2.5 py-2">Work item</th><th className="px-2.5 py-2">Material</th>
                          <th className="px-2.5 py-2 text-right">Qty per unit</th><th className="px-2.5 py-2 text-right">Wastage %</th><th className="px-2.5 py-2">Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => (
                          <tr key={`${r.boq_item_id}-${r.item_id}`} className={cn('border-t border-border align-top', (r.status === 'unit' || r.status === 'no_material') && 'bg-danger-soft/40')}>
                            <td className="px-2.5 py-2">{r.boq_item}<div className="text-xs text-muted-foreground">per {r.boq_uom || 'unit'}</div></td>
                            <td className="px-2.5 py-2"><span className="font-mono text-xs text-muted-foreground">{r.work_code}</span> {r.work_name}<div className="text-xs text-muted-foreground">per {r.work_uom || 'unit'}</div></td>
                            <td className="px-2.5 py-2">{r.item_name}<div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></td>
                            <td className="px-2.5 py-2 text-right tabular-nums">{num(r.qty_per_unit)} {r.base_uom}</td>
                            <td className="px-2.5 py-2 text-right tabular-nums">{num(r.wastage_pct)}</td>
                            <td className="px-2.5 py-2">
                              <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>
                              {r.current && r.status !== 'unchanged' && <div className="mt-0.5 text-xs text-muted-foreground">here now {num(r.current.qty_per_unit)} at {num(r.current.wastage_pct)}%</div>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
        </div>
      )}
      <ConfirmDialog open={confirming} onOpenChange={(o) => !o && setConfirming(false)} title={`Bring in ${taking} norm${taking === 1 ? '' : 's'}?`}
        description={`Into ${projectLabel}, ${mode === 'replace' ? 'replacing the matching norms already set here' : 'keeping every norm already set here'}. Norms here with no work item norm are not touched.`}
        confirmLabel="Bring in" loading={save.isPending} onConfirm={() => save.mutate()} />
    </Modal>
  )
}
