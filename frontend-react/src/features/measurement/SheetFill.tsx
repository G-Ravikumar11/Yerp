import { useRef, useState } from 'react'
import { FileDown, FileUp } from 'lucide-react'
import { Button } from '@/components/ui'
import { importBook, mbKeys, type ImportDim, type ImportSection } from '@/api/mb'
import { useAction } from '@/lib/mutate'
import type { DimLine } from '@/lib/measure'
import { formatQty } from '@/lib/format'

/** One entry of a sheet: a block of lines as the site wrote them, ready to load into the window. */
export interface SheetEntry {
  location: string
  multiplier: number
  dims: ImportDim[]
}

export const toDimLine = (d: ImportDim): DimLine => ({
  particulars: d.particulars ?? '',
  nos: d.nos ?? null,
  nom: d.nom ?? null,
  length: d.length ?? null,
  breadth: d.breadth ?? null,
  depth: d.depth ?? null,
  deduct: !!d.deduct,
  heading: !!d.is_heading,
})

type Found = { source: string; matched: boolean; sections: ImportSection[] }

/**
 * Fill the lines from the measurement book as the site keeps it in Excel, instead of typing them.
 * The sheet is read but nothing is recorded: the lines land in the grid to be checked first.
 */
export function SheetFill({ orderId, itemId, itemName, onUse, onRecorded }: { orderId: number; itemId: number; itemName?: string; onUse: (entry: SheetEntry, source: string) => void; onRecorded?: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [reading, setReading] = useState(false)
  const [error, setError] = useState('')
  const [found, setFound] = useState<Found | null>(null)
  const [file, setFile] = useState<File | null>(null)
  // Entries ticked to be recorded, as "section:entry" - for a workbook with many blocks, all at once.
  const [ticked, setTicked] = useState<Set<string>>(new Set())
  const everyEntry = (f: Found) => f.sections.flatMap((sec) => sec.entries.map((e, i) => ({ key: `${sec.index}:${i}`, sec, e, i })).filter((x) => x.e.dims?.length))
  // Select all leaves out a block that is already in the book: ticking one by hand is a decision.
  const newEntries = (f: Found) => everyEntry(f).filter((x) => !x.e.already_in_book)
  const recordTicked = useAction(
    () => {
      const pairs = [...ticked].map((k) => k.split(':').map(Number) as [number, number])
      // Every section of the sheet is for this item; only the ticked entries are written.
      const mapping = Object.fromEntries((found?.sections ?? []).map((sec) => [sec.index, itemId]))
      return importBook(orderId, file!, { commit: true, mapping, entries: pairs })
    },
    { invalidate: [mbKeys.all, ['subbills']], onSuccess: () => { setFound(null); setTicked(new Set()); onRecorded?.() } },
  )

  const read = async (file: File) => {
    setReading(true)
    setError('')
    setFound(null)
    setTicked(new Set())
    setFile(file)
    try {
      const out = await importBook(orderId, file, { commit: false, includeDims: true })
      const source = `${file.name} / ${out.sheet}`.slice(0, 120)
      const mine = out.sections.filter((s) => s.item_id === itemId)
      const shown = mine.length ? mine : out.sections
      const only = mine.length === 1 && mine[0].entries.length === 1 ? mine[0].entries[0] : null
      if (only?.dims?.length) onUse({ location: only.location, multiplier: only.multiplier, dims: only.dims }, source)
      else setFound({ source, matched: mine.length > 0, sections: shown })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That file could not be read.')
    } finally {
      setReading(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <div className="mb-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] text-muted-foreground">Have the lines in Excel?</span>
        <Button variant="outline" size="sm" asChild>
          <a href="/api/sub-mb/template.xlsx">
            <FileDown /> Template (Excel)
          </a>
        </Button>
        <Button variant="outline" size="sm" loading={reading} onClick={() => input.current?.click()}>
          <FileUp /> Import from Excel
        </Button>
        <input
          ref={input}
          type="file"
          accept=".xlsx,.xlsm"
          className="sr-only"
          tabIndex={-1}
          aria-label="Excel file to read the lines from"
          onChange={(e) => e.target.files?.[0] && void read(e.target.files[0])}
        />
      </div>
      {error && (
        <p role="alert" className="mt-2 text-[13px] text-danger">
          {error}
        </p>
      )}
      {found && (
        <div className="mt-3 rounded-lg border border-border bg-card p-3">
          <p className="mb-2 text-[13px] text-muted-foreground">
            {found.matched ? 'This item is in the sheet more than once. Choose the entry to load:' : `Nothing in the sheet is named like ${itemName || 'this item'}. These are the sections it has - load one only if it is the same work:`}
          </p>
          <div className="mb-2 flex flex-wrap items-center gap-3 text-[13px]">
            <label className="flex items-center gap-2">
              <input type="checkbox" aria-label="Select every entry" checked={ticked.size > 0 && ticked.size === newEntries(found).length} onChange={(e) => setTicked(e.target.checked ? new Set(newEntries(found).map((x) => x.key)) : new Set())} />
              Select all {newEntries(found).length} new entries
            </label>
            <span className="text-muted-foreground">{ticked.size} ticked</span>
            <Button size="sm" className="ml-auto" disabled={!ticked.size} loading={recordTicked.isPending} onClick={() => recordTicked.mutate()}>
              Record {ticked.size || ''} ticked as entries on this item
            </Button>
          </div>
          <ul className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
            {everyEntry(found).map(({ key, sec, e }) => (
              <li key={key} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  aria-label={`Tick ${sec.description}${e.location ? ' ' + e.location : ''}`}
                  checked={ticked.has(key)}
                  onChange={(ev) => setTicked((t) => { const n = new Set(t); if (ev.target.checked) n.add(key); else n.delete(key); return n })}
                />
                <button
                  type="button"
                  title="Load just this one into the grid below, to check it first"
                  onClick={() => {
                    onUse({ location: e.location, multiplier: e.multiplier, dims: e.dims ?? [] }, found.source)
                    setFound(null)
                  }}
                  className="flex min-w-0 flex-1 items-baseline gap-2 rounded-md border border-border px-3 py-1.5 text-left text-[13px] transition-colors hover:bg-accent"
                >
                  <span className="min-w-0 flex-1 truncate">
                    <span className="font-medium">{sec.description}</span>
                    {e.location ? ` · ${e.location}` : ''}
                  </span>
                  <span className="tabular shrink-0 text-muted-foreground">
                    {e.lines} lines · {formatQty(e.quantity)}
                    {e.multiplier !== 1 ? ` · ${e.multiplier} blocks` : ''}
                    {(e.held_back ?? 0) > 0 ? ` · pays ${formatQty(e.quantity)} of ${formatQty(e.full_quantity)}` : ''}
                  </span>
                  {e.already_in_book && <span className="shrink-0 rounded bg-warning-soft px-1.5 py-0.5 text-[11px] text-warning">already in the book</span>}
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">Tick the entries that belong to this item and record them in one go, or click one to load it into the grid and check it first. Nothing goes past what the order allows.</p>
        </div>
      )}
    </div>
  )
}
