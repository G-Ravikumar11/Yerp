import { useRef, useState } from 'react'
import { Check, Download, FileSpreadsheet, FileText, Printer } from 'lucide-react'
import { Button, Modal, Tabs } from '@/components/ui'
import type { Statement } from '@/api/rfq'
import { comparisonUrl, type DocFormat } from '@/lib/rfqCompare'
import { cn } from '@/lib/utils'

/** The comparative statement as a document: pick PDF or Excel and the suppliers to put in it, read it here, then save or print it. */
export function ComparisonDocModal({ statement, initial, open, onClose }: { statement: Statement; initial: string[]; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="xl" title={`${statement.rfq.number}: the comparative statement`} description="Pick PDF or Excel and the suppliers to include. The PDF is the sheet to print and sign; the Excel is the same figures to work on.">
      {open && <Body statement={statement} initial={initial} />}
    </Modal>
  )
}

function Body({ statement, initial }: { statement: Statement; initial: string[] }) {
  const [format, setFormat] = useState<DocFormat>('pdf')
  const [chosen, setChosen] = useState(initial)
  const frame = useRef<HTMLIFrameElement>(null)
  const sups = statement.suppliers
  const id = statement.rfq.id
  const url = comparisonUrl(id, format, chosen, sups.length)
  const toggle = (name: string) => setChosen((c) => (c.includes(name) ? c.filter((n) => n !== name) : [...c, name]))
  const none = chosen.length === 0
  const print = () => {
    try { frame.current?.contentWindow?.print() } catch { window.open(url, '_blank', 'noopener') }
  }
  const label = format === 'pdf' ? 'PDF' : 'Excel'
  return (
    <div className="grid gap-4 md:grid-cols-[240px_1fr]">
      <div className="flex flex-col gap-4">
        <div>
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">Format</p>
          <Tabs label="Format" value={format} onChange={setFormat} items={[{ value: 'pdf', label: 'PDF' }, { value: 'xlsx', label: 'Excel' }] as const} />
        </div>
        <div className="min-h-0 flex-1">
          <div className="mb-1.5 flex items-center justify-between">
            <p className="text-xs font-medium text-muted-foreground" aria-live="polite">{none ? 'Choose at least one supplier' : `Suppliers · ${chosen.length} of ${sups.length}`}</p>
            <div className="flex gap-2 text-xs">
              <button type="button" className="text-primary hover:underline" onClick={() => setChosen(sups.map((s) => s.supplier_name))}>All</button>
              <button type="button" className="text-primary hover:underline" onClick={() => setChosen([])}>None</button>
            </div>
          </div>
          <div role="group" aria-label="Suppliers in the document" className="grid max-h-[28vh] gap-1 overflow-y-auto rounded-lg border border-border p-1.5 md:max-h-[44vh]">
            {sups.map((s) => {
              const on = chosen.includes(s.supplier_name)
              return (
                <button key={s.quote_id} type="button" aria-pressed={on} onClick={() => toggle(s.supplier_name)}
                  className={cn('flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors', on ? 'bg-primary-soft text-foreground' : 'text-muted-foreground hover:bg-accent')}>
                  <span className={cn('grid size-4 shrink-0 place-items-center rounded-md border', on ? 'border-primary bg-primary text-primary-foreground' : 'border-input')}>{on && <Check className="size-3" />}</span>
                  <span className="min-w-0 flex-1 truncate">{s.supplier_name}</span>
                  {s.rank && <span className="text-[10px] font-semibold text-muted-foreground">{s.rank}</span>}
                </button>
              )
            })}
          </div>
        </div>
        <div className="grid gap-2">
          {none
            ? <Button disabled><Download /> Download {label}</Button>
            : <Button asChild><a href={url} download><Download /> Download {label}</a></Button>}
          {format === 'pdf' && (
            <div className="grid grid-cols-2 gap-2">
              <Button variant="outline" disabled={none} onClick={print}><Printer /> Print</Button>
              {none ? <Button variant="outline" disabled><FileText /> Open</Button> : <Button variant="outline" asChild><a href={url} target="_blank" rel="noopener"><FileText /> Open</a></Button>}
            </div>
          )}
        </div>
      </div>
      <div className="min-w-0">
        {format === 'pdf' ? (
          none
            ? <div className="grid h-[70vh] place-items-center rounded-lg border border-border bg-surface text-sm text-muted-foreground">Choose the suppliers to put in the document.</div>
            : <iframe ref={frame} key={url} title="Comparative statement" src={url} className="h-[70vh] w-full rounded-lg border border-border bg-white" />
        ) : (
          <div className="grid h-[70vh] place-items-center rounded-lg border border-border bg-surface p-6 text-center">
            <div className="grid max-w-sm justify-items-center gap-2">
              <FileSpreadsheet className="size-12 text-success" />
              <div className="font-semibold">comparison_{statement.rfq.number}.xlsx</div>
              <p className="text-[13px] text-muted-foreground">{none ? 'Choose the suppliers to put in the workbook.' : `${statement.lines.length} lines against ${chosen.length} ${chosen.length === 1 ? 'supplier' : 'suppliers'}, with each supplier's basic, GST, freight, landed total and rank. A workbook opens in Excel, so it is not previewed here.`}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
