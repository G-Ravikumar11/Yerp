import { useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Redo2, RotateCcw, Rows3, Undo2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataGrid, type ChangeInfo, type Column, type GridHandle } from '@/components/grid'
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui'
import { blankDim, dimQty, dimTotal, type DimLine } from '@/lib/measure'
import { compactINR, formatINR } from '@/lib/utils'

/* --- A work order's schedule of quantities ------------------------------ */

interface BoqLine {
  activity: string
  description: string
  uom: string
  qty: number | null
  rate: number | null
  tolerance: number | null
  done: boolean
}

const blankBoq = (): BoqLine => ({ activity: '', description: '', uom: 'cum', qty: null, rate: null, tolerance: null, done: false })

const UOMS = ['cum', 'sqm', 'rmt', 'MT', 'nos', 'kg', 'ltr', 'LS']

const sampleBoq = (): BoqLine[] => [
  { activity: '1.0', description: 'M25 grade RMC pouring, cube strength 25 MPa, 14-day curing', uom: 'cum', qty: 250, rate: 6800, tolerance: 5, done: false },
  { activity: '2.0', description: 'Fe500D reinforcement steel, cut, bent and placed', uom: 'MT', qty: 18.5, rate: 68000, tolerance: 2, done: false },
  { activity: '3.0', description: 'Shuttering for slabs and beams, ply and props', uom: 'sqm', qty: 1450, rate: 410, tolerance: null, done: false },
  { activity: '4.0', description: 'Brick masonry in cement mortar 1:6, 230 mm', uom: 'cum', qty: 96, rate: 5900, tolerance: null, done: false },
]

const boqColumns: Column<BoqLine>[] = [
  { id: 'activity', header: 'Activity', hint: 'No.', width: 96, mono: true, pin: true, placeholder: '5.0' },
  { id: 'description', header: 'Description of work', hint: 'What the gang is to do', width: 380, required: true, placeholder: 'What is the work?' },
  { id: 'uom', header: 'UoM', type: 'select', options: UOMS, width: 96 },
  {
    id: 'qty',
    header: 'Ordered',
    hint: 'Quantity',
    type: 'number',
    decimals: 2,
    width: 120,
    validate: (v) => ((v as number) <= 0 ? 'Must be more than nought' : null),
  },
  {
    id: 'rate',
    header: 'Rate',
    hint: '₹ per unit',
    type: 'number',
    decimals: 2,
    width: 130,
    validate: (v) => ((v as number) < 0 ? 'Cannot be negative' : null),
  },
  {
    id: 'amount',
    header: 'Amount',
    hint: 'Ordered x rate',
    type: 'number',
    width: 160,
    readOnly: true,
    get: (r) => (r.qty && r.rate ? Math.round(r.qty * r.rate * 100) / 100 : null),
    format: (v) => (typeof v === 'number' ? formatINR(v) : ''),
    summary: 'sum',
  },
  { id: 'tolerance', header: 'Tolerance', hint: '% over allowed', type: 'number', decimals: 1, width: 116, validate: (v) => ((v as number) < 0 || (v as number) > 50 ? '0 to 50' : null) },
  { id: 'done', header: 'Priced', type: 'checkbox', width: 84 },
]

/* --- The measurement book's dimension lines ----------------------------- */

const dimColumns: Column<DimLine>[] = [
  { id: 'particulars', header: 'Particulars', hint: 'Slab, Beam, Deductions...', width: 260, pin: true, placeholder: 'What was measured?' },
  { id: 'nos', header: "No's", type: 'number', width: 84 },
  { id: 'nom', header: 'NoM', hint: 'Times', type: 'number', width: 84 },
  { id: 'length', header: 'Length', hint: 'm', type: 'number', decimals: 3, width: 104 },
  { id: 'breadth', header: 'Breadth', hint: 'm', type: 'number', decimals: 3, width: 104 },
  { id: 'depth', header: 'Depth', hint: 'm', type: 'number', decimals: 3, width: 104 },
  { id: 'deduct', header: 'Deduct', type: 'checkbox', width: 84 },
  { id: 'heading', header: 'Heading', type: 'checkbox', width: 84 },
  {
    id: 'quantity',
    header: 'Quantity',
    hint: 'Worked out',
    type: 'number',
    decimals: 3,
    width: 130,
    readOnly: true,
    get: (r) => dimQty(r),
    summary: (rows) => dimTotal(rows).toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 }),
  },
]

const sampleDims = (): DimLine[] => [
  { ...blankDim(), particulars: 'Block C-3, first floor', heading: true },
  { ...blankDim(), particulars: 'Slab', nos: 1, nom: 1, length: 12.5, breadth: 8 },
  { ...blankDim(), particulars: 'Beam', nos: 4, nom: 1, length: 6, breadth: 0.6 },
  { ...blankDim(), particulars: 'Deductions', heading: true },
  { ...blankDim(), particulars: 'Staircase opening', nos: 1, length: 2.4, breadth: 1.2, deduct: true },
]

function Undoable({ handle, last }: { handle: React.RefObject<GridHandle | null>; last: ChangeInfo | null }) {
  return (
    <div className="flex items-center gap-2">
      <span className="hidden text-xs text-muted-foreground sm:inline">{last ? `Last change: ${last.kind}` : 'No changes yet'}</span>
      <Button size="sm" variant="outline" onClick={() => handle.current?.undo()}>
        <Undo2 /> Undo
      </Button>
      <Button size="sm" variant="outline" onClick={() => handle.current?.redo()}>
        <Redo2 /> Redo
      </Button>
    </div>
  )
}

export default function GridPlayground() {
  const [boq, setBoq] = useState<BoqLine[]>(sampleBoq)
  const [dims, setDims] = useState<DimLine[]>(sampleDims)
  const [big, setBig] = useState<BoqLine[] | null>(null)
  const [lastBoq, setLastBoq] = useState<ChangeInfo | null>(null)
  const [lastDims, setLastDims] = useState<ChangeInfo | null>(null)
  const boqRef = useRef<GridHandle>(null)
  const dimRef = useRef<GridHandle>(null)

  const order = useMemo(() => boq.reduce((s, r) => s + (r.qty && r.rate ? r.qty * r.rate : 0), 0), [boq])

  const loadBig = () =>
    setBig(
      Array.from({ length: 5000 }, (_, i) => ({
        activity: `${Math.floor(i / 10) + 1}.${i % 10}`,
        description: `Item ${i + 1} - ${['Excavation', 'PCC', 'Footing', 'Column', 'Slab', 'Plaster'][i % 6]}`,
        uom: UOMS[i % UOMS.length],
        qty: (i % 40) + 1,
        rate: 100 + (i % 17) * 25,
        tolerance: null,
        done: i % 3 === 0,
      })),
    )

  return (
    <>
      <PageHeader
        eyebrow="Foundation"
        title="Data grid"
        description="The keyboard-first sheet every data-entry screen is built on. Click a cell and just type; nothing here needs the mouse."
        actions={
          <Button variant="outline" asChild>
            <Link to="/design">
              <ArrowLeft /> Design system
            </Link>
          </Button>
        }
      />

      <Card className="mb-8">
        <CardHeader>
          <CardTitle>Keys</CardTitle>
          <CardDescription>The same as Excel, so nobody has to learn them.</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-8 gap-y-2 text-[13px] sm:grid-cols-2 lg:grid-cols-3">
            {[
              ['Type', 'replaces the cell'],
              ['Enter / Shift+Enter', 'commit and move down / up'],
              ['Tab / Shift+Tab', 'commit and move right / left'],
              ['F2 or double click', 'edit what is there'],
              ['Esc', 'put it back as it was'],
              ['Arrows, Home, End, PgUp/PgDn', 'walk about'],
              ['Ctrl+Arrow', 'jump to the end of a block'],
              ['Shift+Arrow, Shift+click, drag', 'select a block'],
              ['Ctrl+A / Shift+Space / Ctrl+Space', 'all, row, column'],
              ['Ctrl+C / X / V', 'copy, cut, paste - to and from Excel'],
              ['Delete', 'clear the selection'],
              ['Ctrl+D / Ctrl+R', 'fill down / right'],
              ['Ctrl+Z / Ctrl+Y', 'undo / redo'],
              ['Ctrl+- / Ctrl+Shift++', 'remove / insert rows'],
              ['12.5*8 or =(4+2)*3.5', 'sums work in any number cell'],
              ['Space on a tick box', 'tick or untick'],
            ].map(([k, v]) => (
              <div key={k} className="flex items-baseline gap-2">
                <dt className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground">{k}</dt>
                <dd className="text-muted-foreground">{v}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <section className="mb-10">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">Work order schedule</h2>
            <p className="mt-1 text-[13.5px] text-muted-foreground">
              Order value <span className="tabular font-medium text-foreground">{compactINR(order)}</span> - the amount is worked out; paste a block from Excel to try it.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Undoable handle={boqRef} last={lastBoq} />
            <Button size="sm" variant="ghost" onClick={() => setBoq(sampleBoq())}>
              <RotateCcw /> Reset
            </Button>
          </div>
        </div>
        <DataGrid
          ref={boqRef}
          aria-label="Work order schedule of quantities"
          columns={boqColumns}
          rows={boq}
          onRowsChange={(rows, info) => {
            setBoq(rows)
            setLastBoq(info)
          }}
          newRow={blankBoq}
          minRows={8}
        />
      </section>

      <section className="mb-10">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">Measurement book - dimensions</h2>
            <p className="mt-1 max-w-2xl text-[13.5px] text-muted-foreground">
              No&apos;s x NoM x L x B x D, deductions taken away, headings measure nothing - the same arithmetic as the current book. A blank is not a nought.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Undoable handle={dimRef} last={lastDims} />
            <Button size="sm" variant="ghost" onClick={() => setDims(sampleDims())}>
              <RotateCcw /> Reset
            </Button>
          </div>
        </div>
        <DataGrid
          ref={dimRef}
          aria-label="Measurement dimensions"
          columns={dimColumns}
          rows={dims}
          onRowsChange={(rows, info) => {
            setDims(rows)
            setLastDims(info)
          }}
          newRow={blankDim}
          minRows={6}
          rowClassName={(r) => (r.heading ? 'font-semibold' : undefined)}
        />
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">A big sheet</h2>
            <p className="mt-1 text-[13.5px] text-muted-foreground">Only the rows in view are drawn, so five thousand scroll and edit as smoothly as five.</p>
          </div>
          <Button size="sm" variant="outline" onClick={loadBig}>
            <Rows3 /> Load 5,000 rows
          </Button>
        </div>
        {big ? (
          <DataGrid aria-label="Five thousand rows" columns={boqColumns} rows={big} onRowsChange={(rows) => setBig(rows)} newRow={blankBoq} />
        ) : (
          <Card className="grid place-items-center py-14 text-sm text-muted-foreground">Nothing loaded.</Card>
        )}
      </section>
    </>
  )
}
