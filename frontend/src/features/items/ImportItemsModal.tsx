import { useMemo, useRef, useState } from 'react'
import { FileSpreadsheet, Wand2 } from 'lucide-react'
import { Badge, Button, Field, Modal, Select } from '@/components/ui'
import { DataGrid, type Column } from '@/components/grid'
import { analyseItemFile, commitItems, itemKeys, type ImportAnalysis, type ImportRow, type ItemVocabulary } from '@/api/items'
import { useAction } from '@/lib/mutate'
import { toast } from '@/stores/toast'
import { ApiError } from '@/lib/api'

const problemFor = (row: ImportRow, field: string) => row._problems?.find((p) => p.field === field)
const blank = (): ImportRow => ({ _line: 0, _kind: '', item_code: '', item_name: '', item_type: 'Purchased', units_of_measure: 'Nos', hsn_code: '', item_tax_type: '18%' })

/**
 * Any workbook, in whatever columns and order it already has: the server reads
 * it, works out which column is which and repairs what is unambiguous. What is
 * left over is fixed here, on screen, and saved - no trip back to Excel.
 */
export function ImportItemsModal({ open, onOpenChange, vocab }: { open: boolean; onOpenChange: (o: boolean) => void; vocab: ItemVocabulary | undefined }) {
  const [analysis, setAnalysis] = useState<ImportAnalysis | null>(null)
  const [rows, setRows] = useState<ImportRow[]>([])
  const [kind, setKind] = useState('')
  const [busy, setBusy] = useState(false)
  const file = useRef<HTMLInputElement>(null)

  const reset = () => {
    setAnalysis(null)
    setRows([])
    setKind('')
  }

  const commit = useAction(() => commitItems(rows), {
    invalidate: [itemKeys.all],
    success: false,
    onSuccess: (res) => {
      if (res.ok) {
        toast.success(res.message)
        reset()
        onOpenChange(false)
        return
      }
      // Nothing was saved: mark the rows the server objected to and stay put.
      toast.error(res.message)
      setRows((current) =>
        current.map((r) => {
          const errs = res.errors.filter((e) => e.line === r._line)
          return errs.length ? { ...r, _problems: errs.map((e) => ({ field: e.field, message: e.message, fix: null })) } : r
        }),
      )
    },
  })

  const read = async () => {
    const f = file.current?.files?.[0]
    if (!f) return toast.error('Choose a workbook first.')
    setBusy(true)
    try {
      const out = await analyseItemFile(f, kind)
      setAnalysis(out)
      // A sheet with only a description column has no "name" to give: the
      // description stands in, and can be shortened here before saving.
      setRows(
        out.rows.map((r) =>
          !String(r.item_name ?? '').trim() && String(r.description ?? '').trim()
            ? { ...r, item_name: String(r.description).trim(), _problems: r._problems?.filter((p) => p.field !== 'item_name') }
            : r,
        ),
      )
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'Could not read that file.')
    } finally {
      setBusy(false)
    }
  }

  const columns = useMemo<Column<ImportRow>[]>(
    () => [
      { id: '_line', header: 'Line', width: 70, readOnly: true, type: 'number', mono: true },
      { id: '_kind', header: 'Kind', type: 'select', width: 150, required: true, options: [{ value: 'RM', label: 'Raw material' }, { value: 'FG', label: 'Finished good' }] },
      { id: 'item_code', header: 'Code', width: 130, mono: true, validate: (_v, row) => problemFor(row, 'item_code')?.message },
      { id: 'item_name', header: 'Name', width: 300, required: true },
      { id: 'item_type', header: 'Type', type: 'select', width: 130, options: vocab?.item_types ?? ['Purchased', 'Service'] },
      { id: 'units_of_measure', header: 'Unit', type: 'select', width: 110, options: vocab?.units ?? ['Nos'] },
      { id: 'hsn_code', header: 'HSN / SAC', width: 120, mono: true },
      { id: 'item_tax_type', header: 'Tax', type: 'select', width: 100, options: vocab?.tax_rates ?? ['18%'] },
    ],
    [vocab],
  )

  const withFixes = rows.filter((r) => r._problems?.some((p) => p.fix)).length
  const applyFixes = () =>
    setRows((current) =>
      current.map((r) => {
        const fixes = r._problems?.filter((p) => p.fix) ?? []
        if (!fixes.length) return r
        const next: ImportRow = { ...r }
        for (const p of fixes) next[p.field] = p.fix
        next._problems = (r._problems ?? []).filter((p) => !p.fix)
        return next
      }),
    )

  const s = analysis?.summary
  const close = (o: boolean) => {
    if (!o) reset()
    onOpenChange(o)
  }

  return (
    <Modal
      open={open}
      onOpenChange={close}
      size="xl"
      title="Bring items in from Excel"
      description="Any workbook works - your columns, in your order. Anything unclear is fixed here before it is saved."
      footer={
        analysis ? (
          <>
            <Button variant="ghost" onClick={reset}>
              Start again
            </Button>
            <Button loading={commit.isPending} onClick={() => commit.mutate()} disabled={!rows.length}>
              Save {rows.length} item{rows.length === 1 ? '' : 's'}
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={() => close(false)}>
              Cancel
            </Button>
            <Button loading={busy} onClick={read}>
              Read the workbook
            </Button>
          </>
        )
      }
    >
      {!analysis ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="The workbook" htmlFor="ii-file" hint="Excel (.xlsx) or CSV. The first sheet is read unless you pick another after opening it.">
            <input
              id="ii-file"
              ref={file}
              type="file"
              accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
              className="block w-full rounded-md border border-input bg-transparent p-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground"
            />
          </Field>
          <Field label="What are they?" htmlFor="ii-kind" hint="Or let the sheet say: a category column tells them apart.">
            <Select
              id="ii-kind"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              placeholder="Work it out from the sheet"
              options={[
                { value: 'RM', label: 'All raw materials' },
                { value: 'FG', label: 'All finished goods' },
              ]}
            />
          </Field>
          <p className="flex items-center gap-2 text-[13px] text-muted-foreground sm:col-span-2">
            <FileSpreadsheet className="size-4" /> Need a starting point?
            <a className="text-primary underline underline-offset-4" href="/api/erp/items/template">
              Download the template
            </a>
          </p>
        </div>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Badge tone="neutral">{s?.total} rows read</Badge>
            <Badge tone="success" dot>
              {s?.ready} ready
            </Badge>
            {!!s?.blocked && (
              <Badge tone="danger" dot>
                {s.blocked} need attention
              </Badge>
            )}
            {!!s?.repaired && <Badge tone="info">{s.repaired} tidied automatically</Badge>}
            {!!analysis.unknown_kind && <Badge tone="warning">{analysis.unknown_kind} with no kind</Badge>}
            {withFixes > 0 && (
              <Button size="sm" variant="soft" className="ml-auto" onClick={applyFixes}>
                <Wand2 /> Apply {withFixes} suggested fix{withFixes === 1 ? '' : 'es'}
              </Button>
            )}
          </div>
          {analysis.unmapped_headers.length > 0 && (
            <p className="mb-3 text-[13px] text-muted-foreground">Columns not used: {analysis.unmapped_headers.join(', ')}.</p>
          )}
          <DataGrid
            aria-label="Rows read from the workbook"
            columns={columns}
            rows={rows}
            onRowsChange={(next) =>
              // A row that has been touched is no longer what the server flagged; it is checked again on saving.
              setRows((prev) => next.map((r, i) => (prev[i] === r || !r._problems?.length ? r : { ...r, _problems: [] })))
            }
            newRow={blank}
            autoGrow={false}
            maxHeight={360}
          />
        </>
      )}
    </Modal>
  )
}
