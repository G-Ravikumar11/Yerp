import { useState } from 'react'
import { Download, FileSpreadsheet, Upload } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Modal } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { toast } from '@/stores/toast'
import { cn } from '@/lib/utils'
import { commitNormSheet, downloadNormErrors, normTemplateHref, num, previewNormSheet, reportKeys, type ImportMode, type SheetFlag, type SheetPreview, type SheetResult, type SheetRow } from './api'

const ACCEPT = '.xlsx,.xls,.csv'
const FLAG: Record<SheetFlag, string> = { missing_boq: 'BOQ item not found', missing_material: 'Material not found', duplicate: 'Duplicate', invalid_qty: 'Invalid quantity', invalid_wastage: 'Invalid wastage %' }
const ACTION: Record<SheetRow['action'], { label: string; tone: 'success' | 'info' | 'neutral' | 'warning' | 'danger' }> = {
  insert: { label: 'New', tone: 'success' },
  update: { label: 'Will update', tone: 'info' },
  unchanged: { label: 'Same as now', tone: 'neutral' },
  skip: { label: 'Already set - kept', tone: 'warning' },
  error: { label: 'Cannot import', tone: 'danger' },
}

/** Import Excel: choose a sheet, see every row as the server read it, then confirm. Nothing is saved before the confirmation. */
export function NormImportDialog({ projectId, projectLabel, onClose }: { projectId: number; projectLabel: string; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<ImportMode>('add')
  const [preview, setPreview] = useState<SheetPreview | null>(null)
  const [result, setResult] = useState<SheetResult | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [fileError, setFileError] = useState('')
  const [gettingErrors, setGettingErrors] = useState(false)

  const check = useAction((m: ImportMode) => previewNormSheet(file!, projectId, m), { success: false, onSuccess: (p) => setPreview(p) })
  const save = useAction(() => commitNormSheet(file!, projectId, mode), { invalidate: [[...reportKeys.all, 'norms'], ['costs', 'wastage'], ['budgeting']], onSuccess: (r) => { setResult(r); setConfirming(false) }, onError: () => setConfirming(false) })

  const choose = (f: File | null) => {
    setPreview(null)
    setResult(null)
    if (!f) { setFile(null); setFileError(''); return }
    if (!/\.(xlsx|xls|csv)$/i.test(f.name)) { setFile(null); setFileError('Choose an Excel workbook (.xlsx or .xls) or a CSV file.'); return }
    if (f.size > 8_000_000) { setFile(null); setFileError('That file is larger than 8 MB. Split it and import it in parts.'); return }
    setFileError('')
    setFile(f)
  }
  const changeMode = (m: ImportMode) => {
    setMode(m)
    if (preview && file) check.mutate(m)
  }
  const errorReport = async () => {
    if (!file) return
    setGettingErrors(true)
    try { await downloadNormErrors(file, projectId) } catch (e) { toast.error((e as Error).message) } finally { setGettingErrors(false) }
  }

  const s = preview?.summary
  const valid = preview?.rows.filter((r) => r.valid) ?? []
  const invalid = preview?.rows.filter((r) => !r.valid) ?? []
  const toSave = (s?.insert ?? 0) + (s?.update ?? 0)

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title="Import material norms from Excel"
      description={`Into ${projectLabel}. Each row is matched with this project's BOQ and the item master, and shown to you before anything is saved.`}
      footer={result ? <Button onClick={onClose}>Done</Button> : (
        <div className="flex w-full flex-wrap items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          {!preview ? (
            <Button onClick={() => check.mutate(mode)} disabled={!file} loading={check.isPending}><Upload /> Upload and check</Button>
          ) : (
            <Button onClick={() => setConfirming(true)} disabled={toSave === 0 || check.isPending}>Import {toSave} row{toSave === 1 ? '' : 's'}</Button>
          )}
        </div>
      )}>
      {result ? (
        <div className="space-y-3" role="status">
          <p className="text-sm font-medium">{result.message}</p>
          <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-5">
            <Figure label="Added" value={result.inserted} tone="success" />
            <Figure label="Updated" value={result.updated} tone="info" />
            <Figure label="Same as now" value={result.unchanged} />
            <Figure label="Already set - kept" value={result.skipped_existing} />
            <Figure label="Rows with problems" value={result.invalid} tone={result.invalid ? 'danger' : undefined} />
          </dl>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
            <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed border-border p-3 text-sm hover:bg-muted/50">
              <FileSpreadsheet className="size-5 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{file ? file.name : 'Choose the sheet (.xlsx, .xls or .csv)'}</span>
              <input type="file" accept={ACCEPT} className="sr-only" aria-label="Sheet to import" onChange={(e) => choose(e.target.files?.[0] ?? null)} />
              <span className="text-xs font-medium text-primary">Browse</span>
            </label>
            <Button variant="outline" asChild><a href={normTemplateHref(projectId)} download><Download /> Template</a></Button>
          </div>
          {fileError && <p className="text-sm text-danger" role="alert">{fileError}</p>}
          <fieldset className="flex flex-wrap gap-4 text-sm">
            <legend className="mb-1 text-xs font-medium text-muted-foreground">When a BOQ item already has a norm for the material</legend>
            <label className="flex items-center gap-2"><input type="radio" name="nm-mode" checked={mode === 'add'} onChange={() => changeMode('add')} /> Add new norms only - keep the existing ones</label>
            <label className="flex items-center gap-2"><input type="radio" name="nm-mode" checked={mode === 'update'} onChange={() => changeMode('update')} /> Update existing norms, and add new ones</label>
          </fieldset>

          {preview && s && (
            <>
              <div className="flex flex-wrap gap-2 text-xs">
                <Badge tone="neutral">{s.total} rows</Badge>
                <Badge tone="success">{s.insert} new</Badge>
                {s.update > 0 && <Badge tone="info">{s.update} to update</Badge>}
                {s.unchanged > 0 && <Badge tone="neutral">{s.unchanged} same as now</Badge>}
                {s.skip > 0 && <Badge tone="warning">{s.skip} already set</Badge>}
                {s.invalid > 0 && <Badge tone="danger">{s.invalid} with problems</Badge>}
                {s.missing_boq > 0 && <Badge tone="danger">{s.missing_boq} BOQ item not found</Badge>}
                {s.missing_material > 0 && <Badge tone="danger">{s.missing_material} material not found</Badge>}
                {s.duplicate > 0 && <Badge tone="danger">{s.duplicate} duplicate</Badge>}
                {s.invalid_qty > 0 && <Badge tone="danger">{s.invalid_qty} invalid number</Badge>}
              </div>
              {invalid.length > 0 && (
                <section aria-labelledby="nm-bad">
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <h3 id="nm-bad" className="text-sm font-semibold text-danger">Rows that cannot be imported ({invalid.length})</h3>
                    <Button size="sm" variant="outline" onClick={errorReport} loading={gettingErrors}><Download /> Error report</Button>
                  </div>
                  <RowsTable rows={invalid} bad />
                </section>
              )}
              <section aria-labelledby="nm-good">
                <h3 id="nm-good" className="mb-1.5 text-sm font-semibold">Rows ready to import ({valid.length})</h3>
                {valid.length ? <RowsTable rows={valid} /> : <p className="text-sm text-muted-foreground">No row can be imported. Correct the sheet and upload it again.</p>}
              </section>
            </>
          )}
        </div>
      )}
      <ConfirmDialog open={confirming} onOpenChange={(o) => !o && setConfirming(false)} title={`Import ${toSave} norm${toSave === 1 ? '' : 's'}?`}
        description={`${s?.insert ?? 0} will be added${mode === 'update' ? ` and ${s?.update ?? 0} existing norms changed` : ''} in ${projectLabel}.${s?.invalid ? ` ${s.invalid} rows with problems are left out.` : ''} The file is checked again as it is saved; it all goes in or none of it does.`}
        confirmLabel="Import" loading={save.isPending} onConfirm={() => save.mutate()} />
    </Modal>
  )
}

function Figure({ label, value, tone }: { label: string; value: number; tone?: 'success' | 'info' | 'danger' }) {
  return (
    <div className="rounded-lg border border-border p-2.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('text-lg font-semibold tabular-nums', tone === 'success' && 'text-success', tone === 'info' && 'text-info', tone === 'danger' && 'text-danger')}>{value}</dd>
    </div>
  )
}

function RowsTable({ rows, bad }: { rows: SheetRow[]; bad?: boolean }) {
  return (
    <div className="max-h-72 overflow-auto rounded-lg border border-border">
      <table className="w-full min-w-max text-[13px]">
        <thead className="sticky top-0 bg-surface text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-2.5 py-2">Line</th><th className="px-2.5 py-2">BOQ item</th><th className="px-2.5 py-2">Material</th>
            <th className="px-2.5 py-2 text-right">Qty per unit</th><th className="px-2.5 py-2 text-right">Wastage %</th><th className="px-2.5 py-2">{bad ? 'Problem' : 'Will'}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.line} className={cn('border-t border-border align-top', bad && 'bg-danger-soft/40')}>
              <td className="px-2.5 py-1.5 tabular-nums text-muted-foreground">{r.line}</td>
              <td className={cn('px-2.5 py-1.5', r.flags.includes('missing_boq') && 'font-medium text-danger')}>
                {r.boq_item || r.boq_text || <em>blank</em>}{r.boq_item && r.boq_text && r.boq_item !== r.boq_text && <div className="text-xs text-muted-foreground">as written: {r.boq_text}</div>}
              </td>
              <td className={cn('px-2.5 py-1.5', r.flags.includes('missing_material') && 'font-medium text-danger')}>
                {r.item_name || r.material_text || <em>blank</em>}{r.item_code && <div className="font-mono text-xs text-muted-foreground">{r.item_code}</div>}
              </td>
              <td className={cn('px-2.5 py-1.5 text-right tabular-nums', r.flags.includes('invalid_qty') && 'font-medium text-danger')}>{r.qty_per_unit != null ? `${num(r.qty_per_unit)} ${r.base_uom}` : r.qty_text || '-'}</td>
              <td className={cn('px-2.5 py-1.5 text-right tabular-nums', r.flags.includes('invalid_wastage') && 'font-medium text-danger')}>{r.wastage_pct != null ? num(r.wastage_pct) : r.wastage_text || '-'}</td>
              <td className="px-2.5 py-1.5">
                {bad ? (
                  <div className="space-y-1">
                    <div className="flex flex-wrap gap-1">{r.flags.map((f) => <Badge key={f} tone="danger">{FLAG[f]}</Badge>)}</div>
                    <div className="max-w-sm text-xs text-danger">{r.errors.join(' ')}</div>
                  </div>
                ) : (
                  <div>
                    <Badge tone={ACTION[r.action].tone}>{ACTION[r.action].label}</Badge>
                    {r.current && r.action !== 'unchanged' && <div className="mt-0.5 text-xs text-muted-foreground">now {num(r.current.qty_per_unit)} at {num(r.current.wastage_pct)}%</div>}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
