import { useRef, useState } from 'react'
import { FileUp } from 'lucide-react'
import { api, post } from '@/lib/api'
import { Badge, Button, Input, Modal, Select } from '@/components/ui'
import { schKeys } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { useQueryClient } from '@tanstack/react-query'

export interface ImportedRow { kind: 'activity' | 'task'; sno: string; text: string; start: string; finish: string; under?: number }
interface Preview { rows: ImportedRow[]; warnings: string[]; message: string }

/**
 * Import a programme sheet: a block heading, its activities, each one's own stages, read by how it is indented in the
 * sheet. Nothing is saved until Import is pressed - the rows are shown first, with their kind, so one read wrong can
 * be fixed by hand before anything lands on the plan.
 */
export function ImportScheduleModal({ job, open, onClose }: { job: number; open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const file = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [rows, setRows] = useState<ImportedRow[]>([])

  const read = useAction(
    async (f: File) => {
      const form = new FormData()
      form.append('file', f)
      return api<Preview>(`/api/jobs/${job}/schedule/import`, { method: 'POST', body: form })
    },
    { onSuccess: (r) => { setPreview(r); setRows(r.rows) } },
  )
  const confirm = useAction(() => post<{ message: string }>(`/api/jobs/${job}/schedule/import/confirm`, { rows }), {
    success: (r) => r.message,
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: schKeys.all }); close() },
  })

  const close = () => { setPreview(null); setRows([]); onClose() }
  const activityLabel = (i: number) => { const r = rows[i]; return r ? `${r.sno ? r.sno + ' ' : ''}${r.text}`.slice(0, 50) : '' }
  const activityOptions = rows.map((r, i) => (r.kind === 'activity' ? { value: i, label: activityLabel(i) } : null)).filter((x): x is { value: number; label: string } => !!x)

  return (
    <Modal open={open} onOpenChange={(o) => !o && close()} title="Import a programme" description="A block heading, its activities, each one's own stages - read by how the sheet is indented. Nothing is saved until you press Import." size="xl">
      {!preview ? (
        <div className="grid gap-3">
          <input ref={file} type="file" hidden accept=".xlsx" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) read.mutate(f) }} />
          <Button variant="outline" loading={read.isPending} onClick={() => file.current?.click()}><FileUp /> Choose the sheet</Button>
          {read.error && <p role="alert" className="text-[13px] text-danger">{read.error.message}</p>}
          <p className="text-xs text-muted-foreground">Needs a description column and Start / End date columns. SL.No is read if there, but is not required.</p>
        </div>
      ) : (
        <div className="grid gap-3">
          <p className="text-sm">{preview.message}</p>
          {preview.warnings.length > 0 && (
            <div className="rounded-lg border border-warning/40 bg-warning-soft p-2.5 text-[13px]">
              <div className="mb-1 font-semibold">{preview.warnings.length} row{preview.warnings.length === 1 ? '' : 's'} left out</div>
              <ul className="grid gap-0.5">{preview.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </div>
          )}
          <div className="max-h-[26rem] overflow-y-auto rounded-lg border border-border">
            <table aria-label="Rows read from the sheet" className="w-full text-[13px]">
              <thead className="sticky top-0 bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr><th className="px-2 py-2">Kind</th><th className="px-2 py-2">Description</th><th className="px-2 py-2">Under</th><th className="px-2 py-2">Start</th><th className="px-2 py-2">Finish</th></tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className={`border-t border-border ${r.kind === 'activity' ? 'bg-surface/60 font-semibold' : ''}`}>
                    <td className="px-2 py-1.5">
                      <Select
                        aria-label={`Kind of row ${i + 1}`}
                        value={r.kind}
                        onChange={(e) => setRows((prev) => prev.map((x, j) => (j === i ? { ...x, kind: e.target.value as 'activity' | 'task', under: e.target.value === 'activity' ? undefined : x.under } : x)))}
                        options={[{ value: 'activity', label: 'Activity' }, { value: 'task', label: 'Task' }]}
                        className="h-8 text-xs"
                      />
                    </td>
                    <td className="max-w-md px-2 py-1.5"><textarea aria-label={`Description of row ${i + 1}`} value={r.text} rows={1} onChange={(e) => setRows((prev) => prev.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} className="w-full resize-y rounded-md border border-input bg-background px-2 py-1 text-[13px] text-foreground" /></td>
                    <td className="px-2 py-1.5">
                      {r.kind === 'task' ? (
                        <Select aria-label={`Which activity row ${i + 1} is under`} value={r.under ?? ''} onChange={(e) => setRows((prev) => prev.map((x, j) => (j === i ? { ...x, under: Number(e.target.value) } : x)))} options={activityOptions} className="h-8 w-40 text-xs" />
                      ) : <span className="text-muted-foreground">-</span>}
                    </td>
                    <td className="px-2 py-1.5"><Input type="date" aria-label={`Start of row ${i + 1}`} value={r.start} onChange={(e) => setRows((prev) => prev.map((x, j) => (j === i ? { ...x, start: e.target.value } : x)))} className="h-8 text-xs" /></td>
                    <td className="px-2 py-1.5"><Input type="date" aria-label={`Finish of row ${i + 1}`} value={r.finish} onChange={(e) => setRows((prev) => prev.map((x, j) => (j === i ? { ...x, finish: e.target.value } : x)))} className="h-8 text-xs" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground"><Badge tone="neutral">{rows.filter((r) => r.kind === 'activity').length} activities</Badge><Badge tone="neutral">{rows.filter((r) => r.kind === 'task').length} tasks</Badge></div>
        </div>
      )}
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {confirm.error && <p role="alert" className="mr-auto text-[13px] text-danger">{confirm.error.message}</p>}
        <Button variant="ghost" onClick={close}>Cancel</Button>
        {preview && <Button variant="outline" onClick={() => { setPreview(null); setRows([]) }}>Choose a different sheet</Button>}
        {preview && <Button loading={confirm.isPending} disabled={rows.length === 0} onClick={() => confirm.mutate()}>Import</Button>}
      </div>
    </Modal>
  )
}
