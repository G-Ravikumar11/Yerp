import { useRef, useState } from 'react'
import { AlertTriangle, FileSpreadsheet } from 'lucide-react'
import { Badge, Button, Field, Input, Modal, Select } from '@/components/ui'
import { importBook, mbKeys, type ImportPreview } from '@/api/mb'
import { useAction } from '@/lib/mutate'
import { formatQty } from '@/lib/format'
import { ApiError } from '@/lib/api'

/**
 * The measurement book as the site keeps it in Excel, read into the gang's
 * book: each numbered section is matched to an item on the order, the matches
 * can be corrected here, and nothing is recorded until you confirm.
 */
export function ImportBookModal({ orderId, open, onOpenChange }: { orderId: number; open: boolean; onOpenChange: (o: boolean) => void }) {
  const file = useRef<HTMLInputElement>(null)
  const [picked, setPicked] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<Record<number, number | null>>({})
  const [measuredOn, setMeasuredOn] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const [again, setAgain] = useState(false)

  const reset = () => {
    setPicked(null)
    setPreview(null)
    setMapping({})
    setAgain(false)
    setProblem('')
    if (file.current) file.current.value = ''
  }

  const read = async (f: File) => {
    setBusy(true)
    setProblem('')
    try {
      const out = await importBook(orderId, f, { commit: false })
      setPreview(out)
      setMapping(Object.fromEntries(out.sections.map((s) => [s.index, s.item_id])))
    } catch (e) {
      setPreview(null)
      setProblem(e instanceof ApiError ? e.message : 'That file could not be read.')
    } finally {
      setBusy(false)
    }
  }

  const commit = useAction(() => importBook(orderId, picked!, { commit: true, mapping, measuredOn: measuredOn || undefined, allowDuplicates: again }), {
    invalidate: [mbKeys.all, ['subbills']],
    onSuccess: () => {
      reset()
      onOpenChange(false)
    },
    onError: (e) => setProblem(e.message),
  })

  const unmatched = preview ? preview.sections.filter((s) => !mapping[s.index]).length : 0

  return (
    <Modal
      open={open}
      onOpenChange={(o) => {
        if (!o) reset()
        onOpenChange(o)
      }}
      size="xl"
      title="Measurement book from Excel"
      description="The MB sheet as the site keeps it - S.No, Description, UoM, No's, NoM, Length, Width, Height, Total Quantity."
      footer={
        preview ? (
          <>
            <Button variant="ghost" onClick={reset}>
              Choose another
            </Button>
            <Button loading={commit.isPending} disabled={unmatched > 0} onClick={() => commit.mutate()}>
              Record it in the book
            </Button>
          </>
        ) : (
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        )
      }
    >
      {!preview ? (
        <div>
          <p className="mb-4 text-[13.5px] text-muted-foreground">
            Each numbered section is matched to an item on the order; each lettered block under it becomes an entry, and &quot;Total Quantity for 4 Blocks&quot; is counted four times.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="The workbook" htmlFor="ib-file">
              <input
                id="ib-file"
                ref={file}
                type="file"
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) {
                    setPicked(f)
                    void read(f)
                  }
                }}
                className="block w-full rounded-md border border-input bg-transparent p-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground"
              />
            </Field>
            <Field label="Measured on" htmlFor="ib-on" hint="Blank: the date on the sheet, else today.">
              <Input id="ib-on" type="date" value={measuredOn} onChange={(e) => setMeasuredOn(e.target.value)} />
            </Field>
          </div>
          <p className="mt-4 flex items-center gap-2 text-[13px] text-muted-foreground">
            <FileSpreadsheet className="size-4" /> No file to start from?
            <a className="text-primary underline underline-offset-4" href="/api/sub-mb/template.xlsx">
              Download a worked example
            </a>
          </p>
          {busy && <p className="mt-4 text-sm text-muted-foreground">Reading the workbook...</p>}
          {problem && (
            <p role="alert" className="mt-4 flex items-start gap-2 rounded-lg bg-danger-soft p-3 text-[13.5px] text-danger">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {problem}
            </p>
          )}
        </div>
      ) : (
        <div>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Badge tone="neutral">Sheet {preview.sheet}</Badge>
            {preview.meta.contractor && <Badge tone="neutral">{preview.meta.contractor}</Badge>}
            <Badge tone="success" dot>
              {preview.sections.length - unmatched} of {preview.sections.length} sections matched
            </Badge>
            {unmatched > 0 && (
              <Badge tone="danger" dot>
                {unmatched} need an item
              </Badge>
            )}
          </div>
          {preview.warnings.length > 0 && (
            <ul className="mb-4 space-y-1 rounded-lg bg-warning-soft p-3 text-[13px] text-warning">
              {preview.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          {preview.sections.some((s) => s.entries.some((e) => e.already_in_book)) && (
            <label className="mb-3 flex items-start gap-2 rounded-lg border border-warning/40 bg-warning-soft p-3 text-[13px] text-warning">
              <input type="checkbox" className="mt-0.5" checked={again} onChange={(e) => setAgain(e.target.checked)} />
              <span>Some blocks in this sheet are already in the book for the same item. They are left out so nothing is billed twice. Tick to record them again anyway.</span>
            </label>
          )}
          {unmatched > 0 && (
            <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card p-3 text-[13px]">
              <span>{unmatched} section{unmatched === 1 ? ' has' : 's have'} no item.</span>
              <div className="w-72 max-w-full">
                <Select
                  aria-label="Send every section with no item to"
                  value=""
                  placeholder="Send them all to one item..."
                  onChange={(e) => {
                    const id = Number(e.target.value)
                    if (id) setMapping((m) => ({ ...m, ...Object.fromEntries(preview.sections.filter((s) => !m[s.index]).map((s) => [s.index, id])) }))
                  }}
                  options={preview.items.map((i) => ({ value: i.id, label: `${i.label} (${i.uom})` }))}
                />
              </div>
            </div>
          )}
          <div className="overflow-hidden rounded-xl border border-border">
            <table className="w-full text-[13.5px]">
              <thead className="bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">In the sheet</th>
                  <th className="px-3 py-2">Goes to item</th>
                  <th className="px-3 py-2 text-right">Entries</th>
                  <th className="px-3 py-2 text-right">Quantity</th>
                </tr>
              </thead>
              <tbody>
                {preview.sections.map((s) => (
                  <tr key={s.index} className="border-t border-border align-top">
                    <td className="px-3 py-2.5">
                      <div className="font-medium">{s.description}</div>
                      <div className="text-xs text-muted-foreground">Section {s.sno}</div>
                      <details className="mt-1.5 text-xs">
                        <summary className="cursor-pointer text-primary">Look at the {s.entries.length} {s.entries.length === 1 ? 'entry' : 'entries'} before recording</summary>
                        <ul className="mt-1 space-y-0.5 rounded-md border border-border bg-muted/40 p-2">
                          {s.entries.map((e, i) => (
                            <li key={i} className="flex flex-wrap items-baseline justify-between gap-2">
                              <span className="min-w-0 flex-1 truncate">{e.location || s.description}{e.multiplier !== 1 ? ` · ${e.multiplier} blocks` : ''}</span>
                              <span className="tabular shrink-0 font-medium">{formatQty(e.quantity)}</span>
                              {(e.held_back ?? 0) > 0 && <span className="shrink-0 text-muted-foreground">pays {formatQty(e.quantity)} of {formatQty(e.full_quantity)}</span>}
                              {e.already_in_book && <span className="shrink-0 text-warning">already in the book{e.already_quantity ? ` (${formatQty(e.already_quantity)})` : ''}</span>}
                            </li>
                          ))}
                        </ul>
                      </details>
                    </td>
                    <td className="w-80 max-w-[40vw] px-3 py-2.5">
                      <Select
                        aria-label={`Item for ${s.description}`}
                        value={mapping[s.index] ?? ''}
                        onChange={(e) => setMapping((m) => ({ ...m, [s.index]: e.target.value ? Number(e.target.value) : null }))}
                        placeholder="Choose the item"
                        aria-invalid={!mapping[s.index] ? true : undefined}
                        options={preview.items.map((i) => ({ value: i.id, label: `${i.label} (${i.uom})` }))}
                      />
                    </td>
                    <td className="tabular px-3 py-2.5 text-right">
                      {s.entries.length}
                      {s.entries.some((e) => e.already_in_book) && <div className="text-xs font-normal text-warning">{s.entries.filter((e) => e.already_in_book).length} already in the book, left out</div>}
                    </td>
                    <td className="tabular px-3 py-2.5 text-right font-medium">
                      {formatQty(s.quantity)} {s.uom}
                      {s.entries.some((e) => (e.held_back ?? 0) > 0) && (
                        <div className="text-xs font-normal text-muted-foreground">
                          after holding back {formatQty(s.entries.reduce((n, e) => n + (e.held_back ?? 0), 0))}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {problem && (
            <p role="alert" className="mt-4 rounded-lg bg-danger-soft p-3 text-[13.5px] text-danger">
              {problem}
            </p>
          )}
          <p className="mt-3 text-xs text-muted-foreground">All of it goes in, or none of it does: if any entry would take an item past what the order allows, nothing is recorded.</p>
        </div>
      )}
    </Modal>
  )
}
