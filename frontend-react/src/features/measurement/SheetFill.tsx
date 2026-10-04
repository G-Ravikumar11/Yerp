import { useRef, useState } from 'react'
import { FileDown, FileUp } from 'lucide-react'
import { Button } from '@/components/ui'
import { importBook, type ImportDim, type ImportSection } from '@/api/mb'
import type { DimLine } from '@/lib/measure'
import { formatQty } from '@/lib/format'
import type { Loaded, LoadedBlock, LoadedHold } from './SheetBlocks'

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

type Found = { source: string; matched: boolean; sections: ImportSection[]; warnings: string[] }
type Row = { key: string; sec: ImportSection; e: ImportSection['entries'][number]; i: number }

/**
 * Fill the lines from the measurement book as the site keeps it in Excel, instead of typing them.
 * The sheet is read but nothing is recorded: whatever is chosen - one entry, several, or all - lands in the
 * grid to be checked, with the sheet's hold under each group of blocks.
 */
export function SheetFill({ orderId, itemId, itemName, onLoad }: { orderId: number; itemId: number; itemName?: string; onLoad: (loaded: Loaded) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [reading, setReading] = useState(false)
  const [error, setError] = useState('')
  const [found, setFound] = useState<Found | null>(null)
  // Entries ticked to load, as "section:entry".
  const [ticked, setTicked] = useState<Set<string>>(new Set())
  const everyEntry = (f: Found): Row[] => f.sections.flatMap((sec) => sec.entries.map((e, i) => ({ key: `${sec.index}:${i}`, sec, e, i })).filter((x) => x.e.dims?.length))
  // Select all leaves out a block that is already in the book: ticking one by hand is a decision.
  const newEntries = (f: Found) => everyEntry(f).filter((x) => !x.e.already_in_book)

  const load = (rows: Row[]) => {
    if (!found || !rows.length) return
    const holds: Record<string, LoadedHold> = {}
    const blocks: LoadedBlock[] = rows.map(({ key, sec, e }) => {
      const group = e.group ? `${sec.index}-${e.group}` : ''
      const hold = e.group ? sec.holds?.find((h) => h.group === e.group) : undefined
      if (group && hold && !holds[group]) holds[group] = { reason: hold.reason, percent: hold.percent }
      return {
        key,
        location: e.location,
        multiplier: e.multiplier > 0 ? e.multiplier : 1,
        dims: (e.dims ?? []).map(toDimLine),
        group,
        section: `${sec.sno} ${sec.description}`.trim(),
        letter: '',
      }
    })
    onLoad({ blocks, holds, source: found.source })
    setFound(null)
    setTicked(new Set())
  }

  const read = async (file: File) => {
    setReading(true)
    setError('')
    setFound(null)
    setTicked(new Set())
    try {
      const out = await importBook(orderId, file, { commit: false, includeDims: true })
      const source = `${file.name} / ${out.sheet}`.slice(0, 120)
      const mine = out.sections.filter((s) => s.item_id === itemId)
      const shown = mine.length ? mine : out.sections
      setFound({ source, matched: mine.length > 0, sections: shown, warnings: out.warnings ?? [] })
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
            {found.matched ? 'The sheet has these entries for this item.' : `Nothing in the sheet is named like ${itemName || 'this item'}. These are the sections it has - load only what is the same work.`} Tick them, or click one, to load them into the grid below.
          </p>
          {found.warnings.length > 0 && (
            <ul role="alert" aria-label="What the sheet says about itself" className="mb-2 list-disc rounded-md bg-warning-soft px-5 py-2 text-[13px] text-warning">
              {found.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          <div className="mb-2 flex flex-wrap items-center gap-3 text-[13px]">
            <label className="flex items-center gap-2">
              <input type="checkbox" aria-label="Select every entry" checked={ticked.size > 0 && ticked.size === newEntries(found).length} onChange={(e) => setTicked(e.target.checked ? new Set(newEntries(found).map((x) => x.key)) : new Set())} />
              Select all {newEntries(found).length} new entries
            </label>
            <span className="text-muted-foreground">{ticked.size} ticked</span>
            <Button size="sm" className="ml-auto" disabled={!ticked.size} onClick={() => load(everyEntry(found).filter((x) => ticked.has(x.key)))}>
              Load {ticked.size || ''} into the grid
            </Button>
          </div>
          <ul className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
            {everyEntry(found).map((row) => {
              const { key, sec, e } = row
              return (
                <li key={key} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    aria-label={`Tick ${sec.description}${e.location ? ' ' + e.location : ''}`}
                    checked={ticked.has(key)}
                    onChange={(ev) =>
                      setTicked((t) => {
                        const n = new Set(t)
                        if (ev.target.checked) n.add(key)
                        else n.delete(key)
                        return n
                      })
                    }
                  />
                  <button
                    type="button"
                    title="Load just this one into the grid below, to check it first"
                    onClick={() => load([row])}
                    className="flex min-w-0 flex-1 items-baseline gap-2 rounded-md border border-border px-3 py-1.5 text-left text-[13px] transition-colors hover:bg-accent"
                  >
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-medium">{sec.description}</span>
                      {e.location ? ` · ${e.location}` : ''}
                    </span>
                    <span className="tabular shrink-0 text-muted-foreground">
                      {e.lines} lines · {formatQty(e.quantity)}
                      {e.multiplier !== 1 ? ` · ${e.multiplier} blocks` : ''}
                      {(e.held_back ?? 0) > 0 ? ` · ${formatQty(e.held_back)} held` : ''}
                    </span>
                    {e.already_in_book && <span className="shrink-0 rounded bg-warning-soft px-1.5 py-0.5 text-[11px] text-warning">already in the book</span>}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
