import { useMemo, useState } from 'react'
import { Copy } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Field, Modal, Select } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'
import { copyNorms, num, reportKeys, useCopyPreview, useCopySources, type CopyMode, type CopyResult, type CopyRow } from './api'

const STATUS: Record<CopyRow['status'], { label: string; tone: 'success' | 'info' | 'neutral' | 'warning' | 'danger' }> = {
  insert: { label: 'Will be added', tone: 'success' },
  update: { label: 'Will replace', tone: 'info' },
  unchanged: { label: 'Same as here', tone: 'neutral' },
  skip: { label: 'Already set here - kept', tone: 'warning' },
  choose: { label: 'Choose the BOQ item', tone: 'warning' },
  no_boq: { label: 'No matching BOQ item - skipped', tone: 'danger' },
  no_material: { label: 'Material not in master - skipped', tone: 'danger' },
}
const MATCH: Record<CopyRow['match'], string> = { exact: 'Same number and description', description: 'Same description', number: 'Same number only - confirm', ambiguous: 'More than one could be it', none: '' }

/** What will happen to a row with the line chosen for it: the server's own status, or - for a row it could not settle - what the
 * chosen line leads to. Rows a person has not confirmed are never sent. */
interface Pick { boq: number; on: boolean }

/** Copy norms from another project: choose the project, see where each of its norms would land in this project's BOQ, confirm. */
export function NormCopyDialog({ projectId, projectLabel, onClose }: { projectId: number; projectLabel: string; onClose: () => void }) {
  const sources = useCopySources(projectId, true)
  const [source, setSource] = useState(0)
  const [mode, setMode] = useState<CopyMode>('add')
  const preview = useCopyPreview(source, projectId, mode)
  // What a person changed, kept against the preview it was made on: a new preview starts from its own defaults again.
  const [changed, setChanged] = useState<{ on: number; picks: Record<number, Partial<Pick>> }>({ on: 0, picks: {} })
  const [confirming, setConfirming] = useState(false)
  const [result, setResult] = useState<CopyResult | null>(null)

  const rows = useMemo(() => preview.data?.rows ?? [], [preview.data])
  const tag = preview.dataUpdatedAt
  const picks = useMemo(() => {
    const own = changed.on === tag ? changed.picks : {}
    const out: Record<number, Pick> = {}
    for (const r of rows) {
      // The sure matches start ticked; anything a person must confirm is left for them.
      const copyable = r.status === 'insert' || r.status === 'update'
      out[r.source_norm_id] = { boq: r.boq_item_id ?? 0, on: copyable && !r.needs_confirmation, ...own[r.source_norm_id] }
    }
    return out
  }, [rows, changed, tag])
  const chosen = useMemo(() => rows.filter((r) => picks[r.source_norm_id]?.on && picks[r.source_norm_id]?.boq), [rows, picks])
  const save = useAction(
    () => copyNorms({ source_project_id: source, project_id: projectId, mode, mappings: chosen.map((r) => ({ source_norm_id: r.source_norm_id, boq_item_id: picks[r.source_norm_id].boq })) }),
    { invalidate: [[...reportKeys.all, 'norms'], [...reportKeys.all, 'norm-sources'], ['costs', 'wastage'], ['budgeting']], onSuccess: (r) => { setResult(r); setConfirming(false) }, onError: () => setConfirming(false) },
  )
  const set = (id: number, p: Partial<Pick>) =>
    setChanged((c) => {
      const base = c.on === tag ? c.picks : {}
      return { on: tag, picks: { ...base, [id]: { ...base[id], ...p } } }
    })
  const s = preview.data?.summary
  const sourceLabel = preview.data?.source.label ?? ''

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title="Copy norms from another project"
      description={`Into ${projectLabel}. Each norm goes to the BOQ item here that is the same work - matched by number and description, never by the other project's BOQ line itself. The other project is only read.`}
      footer={result ? <Button onClick={onClose}>Done</Button> : (
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => setConfirming(true)} disabled={!chosen.length}><Copy /> Copy {chosen.length} norm{chosen.length === 1 ? '' : 's'}</Button>
        </div>
      )}>
      {result ? (
        <div className="space-y-2 text-sm" role="status">
          <p className="font-medium">{result.message}</p>
          <p className="text-muted-foreground">{result.copied} added, {result.updated} replaced, {result.unchanged} already the same, {result.skipped_existing} already set here and kept, {result.not_chosen} of the {result.source_norms} not copied.</p>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_16rem]">
            <Field label="Copy from" htmlFor="nc-src" hint={sources.isError ? 'The projects could not be loaded.' : undefined}>
              <Select id="nc-src" value={source || ''} placeholder={sources.isPending ? 'Loading projects...' : 'Choose a project'} onChange={(e) => setSource(Number(e.target.value) || 0)}
                options={(sources.data ?? []).map((p) => ({ value: p.id, label: `${p.label} - ${p.norms} norm${p.norms === 1 ? '' : 's'}`, disabled: p.norms === 0 }))} />
            </Field>
            <Field label="When a norm is already set here" htmlFor="nc-mode">
              <Select id="nc-mode" value={mode} onChange={(e) => setMode(e.target.value as CopyMode)}
                options={[{ value: 'add', label: 'Add missing norms only' }, { value: 'replace', label: 'Replace matching norms' }]} />
            </Field>
          </div>
          {!source ? <p className="text-sm text-muted-foreground">Choose the project whose norms to copy.</p>
            : preview.isPending ? <p className="text-sm text-muted-foreground" role="status">Matching its BOQ items with this project's...</p>
            : preview.isError ? <p className="text-sm text-danger" role="alert">{(preview.error as Error).message}</p>
            : s && (
              <>
                <div className="flex flex-wrap gap-2 text-xs">
                  <Badge tone="neutral">{s.total} norms in {sourceLabel}</Badge>
                  {s.insert > 0 && <Badge tone="success">{s.insert} to add</Badge>}
                  {s.update > 0 && <Badge tone="info">{s.update} to replace</Badge>}
                  {s.skip > 0 && <Badge tone="warning">{s.skip} already set here</Badge>}
                  {s.needs_confirmation > 0 && <Badge tone="warning">{s.needs_confirmation} need you to confirm the BOQ item</Badge>}
                  {s.no_boq > 0 && <Badge tone="danger">{s.no_boq} BOQ item not matched</Badge>}
                  {s.no_material > 0 && <Badge tone="danger">{s.no_material} material not matched</Badge>}
                </div>
                {!rows.length ? <p className="text-sm text-muted-foreground">That project has no norms to copy.</p> : (
                  <div className="max-h-[26rem] overflow-auto rounded-lg border border-border">
                    <table className="w-full min-w-max text-[13px]">
                      <thead className="sticky top-0 z-10 bg-surface text-left text-xs text-muted-foreground">
                        <tr>
                          <th className="w-8 px-2.5 py-2"><span className="sr-only">Copy</span></th>
                          <th className="px-2.5 py-2">Source BOQ item</th><th className="px-2.5 py-2">Material</th>
                          <th className="px-2.5 py-2 text-right">Qty per unit</th><th className="px-2.5 py-2 text-right">Wastage %</th>
                          <th className="px-2.5 py-2">BOQ item here</th><th className="px-2.5 py-2">Copy status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => {
                          const p = picks[r.source_norm_id] ?? { boq: 0, on: false }
                          const blocked = r.status === 'no_boq' || r.status === 'no_material' || r.status === 'skip' || r.status === 'unchanged'
                          return (
                            <tr key={r.source_norm_id} className={cn('border-t border-border align-top', (r.status === 'no_boq' || r.status === 'no_material') && 'bg-danger-soft/40', r.needs_confirmation && 'bg-warning-soft/40')}>
                              <td className="px-2.5 py-2">
                                <input type="checkbox" aria-label={`Copy the norm of ${r.item_name} for ${r.source_boq_item}`} disabled={blocked || !p.boq} checked={p.on && !!p.boq}
                                  onChange={(e) => set(r.source_norm_id, { on: e.target.checked })} />
                              </td>
                              <td className="px-2.5 py-2">{r.source_boq_item}</td>
                              <td className={cn('px-2.5 py-2', r.status === 'no_material' && 'font-medium text-danger')}>{r.item_name}<div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></td>
                              <td className="px-2.5 py-2 text-right tabular-nums">{num(r.qty_per_unit)} {r.base_uom}</td>
                              <td className="px-2.5 py-2 text-right tabular-nums">{num(r.wastage_pct)}</td>
                              <td className={cn('px-2.5 py-2', r.status === 'no_boq' && 'font-medium text-danger')}>
                                {r.candidates.length > 1 ? (
                                  <Select aria-label={`BOQ item here for ${r.source_boq_item}`} className="h-8 min-w-56 text-[13px]" value={p.boq || ''} placeholder="Choose the BOQ item"
                                    onChange={(e) => set(r.source_norm_id, { boq: Number(e.target.value) || 0, on: !!Number(e.target.value) })}
                                    options={r.candidates.map((c) => ({ value: c.id, label: c.label }))} />
                                ) : r.boq_item ? r.boq_item : 'None in this BOQ'}
                                {MATCH[r.match] && <div className="text-xs text-muted-foreground">{MATCH[r.match]}</div>}
                              </td>
                              <td className="px-2.5 py-2">
                                {r.needs_confirmation && !blocked
                                  ? <Badge tone={p.on && p.boq ? 'success' : 'warning'}>{p.on && p.boq ? 'Confirmed' : 'Tick to confirm'}</Badge>
                                  : <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>}
                                {r.current && r.status !== 'unchanged' && <div className="mt-0.5 text-xs text-muted-foreground">here now {num(r.current.qty_per_unit)} at {num(r.current.wastage_pct)}%</div>}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
        </div>
      )}
      <ConfirmDialog open={confirming} onOpenChange={(o) => !o && setConfirming(false)} title={`Copy ${chosen.length} norm${chosen.length === 1 ? '' : 's'}?`}
        description={`From ${sourceLabel} into ${projectLabel}, ${mode === 'replace' ? 'replacing the matching norms already set here' : 'keeping every norm already set here'}. Norms here that are not in the list are not touched, and ${sourceLabel} is not changed.`}
        confirmLabel="Copy" loading={save.isPending} onConfirm={() => save.mutate()} />
    </Modal>
  )
}
