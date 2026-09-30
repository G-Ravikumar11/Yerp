import { useEffect, useMemo, useRef, useState } from 'react'
import { Download, FileUp } from 'lucide-react'
import { DataGrid, type Column } from '@/components/grid'
import { Button, Modal } from '@/components/ui'
import { checkSheet, importSheet, readSheet, sheetTemplateUrl, type SheetRead, type SheetRow } from '@/api/sheets'
import { useAction } from '@/lib/mutate'
import { useDebounced } from '@/lib/hooks'

/**
 * Bring a list in from any workbook: the columns can be named and ordered however they already come.
 * Every row is shown to be corrected in place, with what is wrong beside it; nothing is saved until it is confirmed.
 */
export function SheetImportModal({ open, onOpenChange, kind, title, intro, confirmLabel, invalidate }: { open: boolean; onOpenChange: (o: boolean) => void; kind: string; title: string; intro: string; confirmLabel: string; invalidate: readonly (readonly unknown[])[] }) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} size="xl" title={title} description={intro}>
      {open && <Body kind={kind} confirmLabel={confirmLabel} invalidate={invalidate} onClose={() => onOpenChange(false)} />}
    </Modal>
  )
}

function Body({ kind, confirmLabel, invalidate, onClose }: { kind: string; confirmLabel: string; invalidate: readonly (readonly unknown[])[]; onClose: () => void }) {
  const file = useRef<HTMLInputElement>(null)
  const [read, setRead] = useState<SheetRead | null>(null)
  const [rows, setRows] = useState<SheetRow[]>([])
  const [problems, setProblems] = useState<Record<string, string[]>>({})
  const [error, setError] = useState('')
  const settled = useDebounced(rows, 500)

  const reading = useAction((f: File) => readSheet(kind, f), {
    success: (r) => r.message,
    onSuccess: (r) => { setRead(r); setRows(r.rows); setProblems(r.problems); setError('') },
    onError: (e) => setError(e.message),
  })
  const bring = useAction(() => importSheet(kind, rows), { invalidate: [...invalidate], onSuccess: onClose })

  // The same checks, on the rows as edited.
  useEffect(() => {
    if (!read || settled === read.rows) return
    let live = true
    checkSheet(kind, settled).then((r) => live && setProblems(r.problems)).catch(() => undefined)
    return () => { live = false }
  }, [settled, read, kind])

  const columns = useMemo<Column<SheetRow>[]>(
    () => [
      ...(read?.columns ?? []).map<Column<SheetRow>>((c) => ({ id: c.key, header: c.label, type: c.number ? 'number' : 'text', width: c.number ? 120 : 170, decimals: c.number ? 2 : undefined })),
      { id: '_check', header: 'Check', width: 280, readOnly: true, get: (_r, i) => (problems[String(i)] ?? []).join('; ') || 'ok' },
    ],
    [read, problems],
  )

  const bad = Object.keys(problems).length
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" loading={reading.isPending} onClick={() => file.current?.click()}><FileUp /> Choose a workbook</Button>
        <Button variant="outline" size="sm" asChild><a href={sheetTemplateUrl(kind)}><Download /> Template</a></Button>
        <input ref={file} type="file" accept=".xlsx,.xlsm,.csv" className="sr-only" tabIndex={-1} aria-label="Workbook to read" onChange={(e) => e.target.files?.[0] && reading.mutate(e.target.files[0])} />
        {read && <span className="text-[13px] text-muted-foreground">{rows.length} row{rows.length === 1 ? '' : 's'}{read.skipped ? `, ${read.skipped} total or blank left out` : ''}</span>}
      </div>
      {error && <p role="alert" className="mb-3 text-[13px] text-danger">{error}</p>}
      {read && (
        <>
          <DataGrid aria-label="Rows to bring in" columns={columns} rows={rows} onRowsChange={setRows} newRow={() => ({})} minRows={1} maxHeight={320} />
          <p className="mt-3 text-[13px] text-muted-foreground">{bad ? <span className="text-warning">{bad} row{bad === 1 ? ' needs' : 's need'} a look - a row with a problem may be left out.</span> : 'Every row reads cleanly.'}</p>
        </>
      )}
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {bring.error && <p role="alert" className="mr-auto text-[13px] text-danger">{bring.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={bring.isPending} disabled={!read || rows.length === 0} onClick={() => bring.mutate()}>{confirmLabel}</Button>
      </div>
    </div>
  )
}
