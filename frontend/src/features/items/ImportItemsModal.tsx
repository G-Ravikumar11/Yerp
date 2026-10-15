import { useRef, useState } from 'react'
import { Download, FileSpreadsheet } from 'lucide-react'
import { Badge, Button, Field, Input, Modal, Select } from '@/components/ui'
import { checkImport, commitImport, previewImport, TEMPLATE_URL, type ImportPreview, type ImportPreviewRow, type ImportResult, type ImportStatus } from '@/api/itemMasterImport'
import { masterKeys, useCategories } from '@/api/itemMaster'
import { itemKeys, type ItemVocabulary } from '@/api/items'
import { ApiError } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { toast } from '@/stores/toast'
import { STATUS_HELP, canImport, chooseAction, editValue, entries, importCount, showing, skippedCsv, tally, willImport } from './importLogic'

const TONE: Record<ImportStatus, 'success' | 'info' | 'warning' | 'danger'> = { New: 'success', Update: 'info', Duplicate: 'warning', Error: 'danger' }

/**
 * A sheet comes in in three steps: choose it, see what each row would do (new, changed, repeated or wrong) and fix or skip
 * rows, then see what was added and download what was left out. Nothing is saved until the second step is confirmed.
 */
export function ImportItemsModal({ open, onOpenChange, vocab }: { open: boolean; onOpenChange: (o: boolean) => void; vocab: ItemVocabulary | undefined }) {
  const file = useRef<HTMLInputElement>(null)
  const cats = useCategories()
  const [busy, setBusy] = useState(false)
  const [rows, setRows] = useState<ImportPreviewRow[] | null>(null)
  const [info, setInfo] = useState<Pick<ImportPreview, 'read_as' | 'unused_columns'>>({})
  const [chosen, setChosen] = useState<Set<number>>(new Set())
  const [dirty, setDirty] = useState(false)
  const [filter, setFilter] = useState<ImportStatus | ''>('')
  const [result, setResult] = useState<ImportResult | null>(null)

  const reset = () => {
    setRows(null)
    setInfo({})
    setChosen(new Set())
    setDirty(false)
    setFilter('')
    setResult(null)
  }
  const close = (o: boolean) => {
    if (!o) reset()
    onOpenChange(o)
  }
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : 'Something went wrong. Try again.')

  const read = async () => {
    const f = file.current?.files?.[0]
    if (!f) return toast.error('Choose your Excel or CSV file first.')
    setBusy(true)
    try {
      const out = await previewImport(f)
      setRows(out.rows)
      setInfo({ read_as: out.read_as, unused_columns: out.unused_columns })
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const recheck = useAction(() => checkImport(entries(rows ?? [], chosen)), {
    success: false,
    onSuccess: (out) => {
      setRows(out.rows)
      setDirty(false)
    },
  })
  const save = useAction(() => commitImport(entries(rows ?? [], chosen)), {
    invalidate: [masterKeys.all, itemKeys.all],
    success: false,
    onSuccess: (out) => setResult(out),
  })

  const edit = (line: number, field: string, value: string) => {
    setRows((r) => editValue(r ?? [], line, field, value))
    setDirty(true)
  }
  const choose = (line: number, action: 'import' | 'skip') => {
    setRows((r) => chooseAction(r ?? [], line, action))
    setChosen((c) => new Set(c).add(line))
  }

  const counts = tally(rows ?? [])
  const shown = showing(rows ?? [], filter)
  const n = importCount(rows ?? [])
  const step = result ? 3 : rows ? 2 : 1

  const download = () => {
    const url = URL.createObjectURL(new Blob([skippedCsv(result?.errors ?? [])], { type: 'text/csv' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: 'items-left-out.csv' })
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Modal
      open={open}
      onOpenChange={close}
      size="xl"
      title="Bring items in from Excel"
      description={step === 1 ? 'Step 1 of 3 - choose your file.' : step === 2 ? 'Step 2 of 3 - check what will happen to each row. Nothing is saved yet.' : 'Step 3 of 3 - done.'}
      footer={
        step === 1 ? (
          <>
            <Button variant="ghost" onClick={() => close(false)}>Cancel</Button>
            <Button loading={busy} onClick={read}>Read my file</Button>
          </>
        ) : step === 2 ? (
          <>
            <Button variant="ghost" onClick={reset}>Start again</Button>
            {dirty && <Button variant="outline" loading={recheck.isPending} onClick={() => recheck.mutate()}>Check my changes</Button>}
            <Button loading={save.isPending} disabled={dirty || n === 0} onClick={() => save.mutate()}>
              {dirty ? 'Check your changes first' : `Import ${n} item${n === 1 ? '' : 's'}`}
            </Button>
          </>
        ) : (
          <Button onClick={() => close(false)}>Done</Button>
        )
      }
    >
      {step === 1 && (
        <div className="grid gap-4">
          <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <FileSpreadsheet className="size-4" /> Start from our sheet so the columns match:
            <Button size="sm" variant="outline" asChild><a href={TEMPLATE_URL}><Download /> Download the template</a></Button>
          </p>
          <Field label="Your file" htmlFor="ii-file" hint="Excel (.xlsx) or CSV, up to 5,000 rows. Columns are matched by their heading, in any order.">
            <input id="ii-file" ref={file} type="file" accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
              className="block w-full rounded-md border border-input bg-transparent p-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground" />
          </Field>
          <ul className="list-disc pl-5 text-sm text-muted-foreground">
            <li>A row with a code that is already in the master updates that item. Cells you leave blank are never wiped.</li>
            <li>A row without a code is given the next free one.</li>
            <li>The same item will not be added twice.</li>
          </ul>
        </div>
      )}

      {step === 2 && rows && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2" role="group" aria-label="Show rows">
            <Button size="sm" variant={filter === '' ? 'primary' : 'outline'} onClick={() => setFilter('')}>All {counts.total}</Button>
            {(['New', 'Update', 'Duplicate', 'Error'] as const).map((s) => (
              <Button key={s} size="sm" variant={filter === s ? 'primary' : 'outline'} disabled={!counts[s.toLowerCase() as keyof typeof counts]} onClick={() => setFilter(filter === s ? '' : s)} title={STATUS_HELP[s]}>
                {s} {counts[s.toLowerCase() as keyof typeof counts]}
              </Button>
            ))}
          </div>
          {!!info.unused_columns?.length && <p className="mb-2 text-[13px] text-muted-foreground">Columns not used: {info.unused_columns.join(', ')}.</p>}
          <div className="max-h-[52vh] overflow-auto rounded-lg border">
            <table className="w-full min-w-[56rem] text-sm" aria-label="Rows read from your file">
              <thead className="sticky top-0 bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-2 py-2">Line</th><th className="px-2 py-2">What will happen</th><th className="px-2 py-2">Code</th>
                  <th className="px-2 py-2">Item name</th><th className="px-2 py-2">Unit</th><th className="px-2 py-2">Category</th><th className="px-2 py-2">Import?</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {shown.map((r) => (
                  <tr key={r.line} className={willImport(r) ? '' : 'bg-muted/20'}>
                    <td className="px-2 py-2 font-mono text-xs">{r.line}</td>
                    <td className="max-w-xs px-2 py-2">
                      <Badge tone={TONE[r.status]}>{r.status}</Badge>
                      <p className="mt-1 text-xs text-muted-foreground">{r.reason}</p>
                    </td>
                    <td className="px-2 py-2"><Input aria-label={`Code, line ${r.line}`} onFocus={(e) => e.target.select()} className="h-8 w-32 font-mono uppercase" value={r.values.item_code ?? ''} onChange={(e) => edit(r.line, 'item_code', e.target.value)} placeholder="Next free" /></td>
                    <td className="px-2 py-2"><Input aria-label={`Name, line ${r.line}`} className="h-8 min-w-48" value={r.values.item_name ?? ''} onChange={(e) => edit(r.line, 'item_name', e.target.value)} /></td>
                    <td className="px-2 py-2">
                      <Input aria-label={`Unit, line ${r.line}`} onFocus={(e) => e.target.select()} className="h-8 w-24" list="ii-units" value={r.values.units_of_measure ?? ''} onChange={(e) => edit(r.line, 'units_of_measure', e.target.value)} />
                    </td>
                    <td className="px-2 py-2">
                      <Select aria-label={`Category, line ${r.line}`} value={r.values.item_category ?? ''} placeholder="None" onChange={(e) => { edit(r.line, 'item_category', e.target.value); edit(r.line, 'item_subcategory', '') }}
                        options={[...(cats.data ?? []).map((c) => ({ value: c.name, label: c.name })), ...(r.values.item_category && !cats.data?.some((c) => c.name === r.values.item_category) ? [{ value: r.values.item_category, label: `${r.values.item_category} (not set up)` }] : [])]} />
                    </td>
                    <td className="px-2 py-2">
                      <label className="flex items-center gap-2">
                        <input type="checkbox" aria-label={`Import line ${r.line}`} checked={willImport(r)} disabled={!canImport(r)} onChange={(e) => choose(r.line, e.target.checked ? 'import' : 'skip')} />
                        <span className="text-xs text-muted-foreground">{willImport(r) ? 'Import' : 'Skip'}</span>
                      </label>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <datalist id="ii-units">{(vocab?.units ?? []).map((u) => <option key={u} value={u} />)}</datalist>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">Fix a cell, then press "Check my changes". Rows with a problem are left out of the import until they are fixed.</p>
        </>
      )}

      {step === 3 && result && (
        <div className="grid gap-4">
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="rounded-lg border p-3"><div className="text-2xl font-semibold">{result.created}</div><div className="text-xs text-muted-foreground">added</div></div>
            <div className="rounded-lg border p-3"><div className="text-2xl font-semibold">{result.updated}</div><div className="text-xs text-muted-foreground">updated</div></div>
            <div className="rounded-lg border p-3"><div className="text-2xl font-semibold">{result.skipped}</div><div className="text-xs text-muted-foreground">left out</div></div>
          </div>
          {result.errors.length > 0 && (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <p className="text-sm font-medium">Rows that were left out</p>
                <Button size="sm" variant="outline" onClick={download}><Download /> Download this list</Button>
              </div>
              <ul className="max-h-60 divide-y overflow-y-auto rounded-md border text-sm">
                {result.errors.map((e) => (
                  <li key={e.line} className="px-3 py-2"><span className="font-mono text-xs">Line {e.line}</span> {e.name || e.code} <span className="text-muted-foreground">- {e.reason}</span></li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
