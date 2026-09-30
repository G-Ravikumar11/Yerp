import { useRef, useState } from 'react'
import { FileDown, FileUp } from 'lucide-react'
import { Button } from '@/components/ui'
import { importBook, type ImportDim, type ImportSection } from '@/api/mb'
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
export function SheetFill({ orderId, itemId, onUse }: { orderId: number; itemId: number; onUse: (entry: SheetEntry, source: string) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [reading, setReading] = useState(false)
  const [error, setError] = useState('')
  const [found, setFound] = useState<Found | null>(null)

  const read = async (file: File) => {
    setReading(true)
    setError('')
    setFound(null)
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
            {found.matched ? 'This item is in the sheet more than once. Choose the entry to load:' : 'No section of the sheet matched this item. Choose the lines to load:'}
          </p>
          <ul className="flex flex-col gap-1.5">
            {found.sections.flatMap((s) =>
              s.entries.map((e, i) => (
                <li key={`${s.index}-${i}`}>
                  <button
                    type="button"
                    disabled={!e.dims?.length}
                    onClick={() => {
                      onUse({ location: e.location, multiplier: e.multiplier, dims: e.dims ?? [] }, found.source)
                      setFound(null)
                    }}
                    className="flex w-full items-baseline gap-2 rounded-md border border-border px-3 py-1.5 text-left text-[13px] transition-colors hover:bg-accent disabled:opacity-50"
                  >
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-medium">{s.description}</span>
                      {e.location ? ` · ${e.location}` : ''}
                    </span>
                    <span className="tabular shrink-0 text-muted-foreground">
                      {e.lines} lines · {formatQty(e.quantity)}
                      {e.multiplier !== 1 ? ` · ${e.multiplier} blocks` : ''}
                    </span>
                  </button>
                </li>
              )),
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
