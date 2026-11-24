import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Download } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, Modal, Stat, StatGrid, Tabs } from '@/components/ui'
import { itemSheetFileUrl, useItemSheet, type ItemSheetLine, type ItemSheetRow, type ItemSheetStatus } from '@/api/itemSheet'
import { useSession } from '@/lib/session'
import { compactINR, formatINR } from '@/lib/utils'
import { formatQty, plural } from '@/lib/format'

type Show = 'all' | 'arrange' | 'over' | 'free'

const TONE: Record<ItemSheetStatus, 'warning' | 'danger' | 'neutral' | 'success'> = {
  'To arrange': 'warning', 'Issued past need': 'danger', 'Not budgeted': 'neutral', Covered: 'success',
}

const q = (v: number, uom: string) => (v ? `${formatQty(v)} ${uom}` : '-')

/**
 * The project's Item sheet: every material its BOQ needs - from the budget's material rows, BOQ quantity x quantity per unit
 * x wastage - added up item by item, beside what has been indented, ordered, issued and is at site, and what is still to arrange.
 */
export default function ItemSheetPage() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const job = Number(params.get('job')) || 0
  const setJob = (id: number) => setParams((p) => { const n = new URLSearchParams(p); if (id) n.set('job', String(id)); else n.delete('job'); return n }, { replace: true })
  const [show, setShow] = useState<Show>('all')
  const [open, setOpen] = useState<ItemSheetRow | null>(null)
  const sheet = useItemSheet(job)
  const s = sheet.data
  const t = s?.totals
  const loading = sheet.isPending && job > 0

  const all = s?.rows ?? []
  const rows = all.filter((r) => (show === 'arrange' ? r.status === 'To arrange' : show === 'over' ? r.status === 'Issued past need' : show === 'free' ? !r.in_master : true))
  const cols: TableColumn<ItemSheetRow>[] = [
    { id: 'item', header: 'Material', sort: (r) => r.item_name, cell: (r) => (
      <div className="min-w-[10rem] max-w-[20rem]">
        <p className="font-medium">{r.item_name}</p>
        <p className="text-xs text-muted-foreground">
          {r.in_master ? <span className="font-mono">{r.item_code}</span> : <span className="text-warning">Not in the item master</span>}
          {r.lines.length > 0 && ` · ${plural(r.lines.length, 'BOQ line')}`}
        </p>
        {r.unit_notes.length > 0 && <p className="text-xs text-warning">{r.unit_notes[0]}</p>}
      </div>) },
    { id: 'req', header: 'Required', align: 'right', sort: (r) => r.required, cell: (r) => (
      <div><p className="font-semibold">{q(r.required, r.uom)}</p>{r.required > r.without_wastage && <p className="text-xs text-muted-foreground">{formatQty(r.without_wastage)} + wastage</p>}</div>) },
    { id: 'ind', header: 'Indented', align: 'right', hideBelow: 'lg', sort: (r) => r.indented, cell: (r) => q(r.indented, r.uom) },
    { id: 'ord', header: 'Ordered', align: 'right', hideBelow: 'md', sort: (r) => r.ordered, cell: (r) => (
      <div><p>{q(r.ordered, r.uom)}</p>{r.on_way > 0 && <p className="text-xs text-muted-foreground">{formatQty(r.on_way)} on its way</p>}</div>) },
    { id: 'iss', header: 'Issued', align: 'right', sort: (r) => r.issued, cell: (r) => <span className={r.status === 'Issued past need' ? 'font-semibold text-danger' : ''}>{q(r.issued, r.uom)}</span> },
    { id: 'site', header: 'At site', align: 'right', hideBelow: 'sm', sort: (r) => r.at_site, cell: (r) => q(r.at_site, r.uom) },
    { id: 'left', header: 'To arrange', align: 'right', sort: (r) => r.to_arrange, cell: (r) => (
      r.to_arrange > 0 ? <div><p className="font-semibold">{q(r.to_arrange, r.uom)}</p>{r.to_arrange_value > 0 && <p className="text-xs text-muted-foreground">{compactINR(r.to_arrange_value)}</p>}</div> : <span className="text-muted-foreground">-</span>) },
    { id: 'status', header: 'Status', hideBelow: 'sm', sort: (r) => r.status, cell: (r) => <Badge tone={TONE[r.status]}>{r.status}</Badge> },
  ]

  return (
    <div>
      <PageHeader eyebrow="Projects" title="Item sheet"
        description="Every material the project's BOQ needs, worked out from the budget, beside what has been indented, ordered, issued and is at site."
        actions={<Button variant="outline" disabled={!s?.boq} onClick={() => window.open(itemSheetFileUrl(job), '_blank')}><Download /> Excel</Button>} />
      <div className="mb-4 flex flex-wrap items-end gap-4"><ProjectPicker value={job} onChange={setJob} id="item-sheet-job" /></div>
      {job === 0 && <Card className="p-6 text-sm text-muted-foreground">Choose a project to see the materials its BOQ needs.</Card>}
      {job > 0 && sheet.isError && <p role="alert" className="text-sm text-danger">Could not load the Item sheet.</p>}
      {job > 0 && s && !s.boq && (
        <Card className="p-6 text-sm text-muted-foreground">This project has no BOQ yet. Add one under Clients &gt; BOQ, then give each line its materials in Budgeting.</Card>
      )}
      {job > 0 && (loading || s?.boq) && (<>
        <StatGrid>
          <Stat label="Materials" value={t ? String(t.items) : '-'} sub={t ? `from ${t.boq_lines_with_materials} of ${plural(t.boq_lines, 'BOQ line')}` : undefined} loading={loading} />
          <Stat label="To arrange" value={t ? String(t.to_arrange) : '-'} tone={t && t.to_arrange ? 'warning' : undefined} sub={t && t.to_arrange_value ? `${compactINR(t.to_arrange_value)} at budget rates` : undefined} loading={loading} />
          <Stat label="Issued past need" value={t ? String(t.over_issued) : '-'} tone={t && t.over_issued ? 'danger' : undefined} loading={loading} />
          <Stat label="Material budget" value={compactINR(t?.value)} loading={loading} />
        </StatGrid>
        {t && t.boq_lines_with_materials < t.boq_lines && (
          <p role="status" className="mt-4 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">
            {plural(t.boq_lines - t.boq_lines_with_materials, 'BOQ line')} {t.boq_lines - t.boq_lines_with_materials === 1 ? 'has' : 'have'} no materials yet, so {t.boq_lines - t.boq_lines_with_materials === 1 ? 'its' : 'their'} needs are not on this sheet.
            {can('budget.edit') && <> <Link className="font-medium underline" to={`/projects/budgeting?job=${job}`}>Add them in Budgeting</Link>.</>}
          </p>
        )}
        {t && t.not_in_master > 0 && (
          <p role="status" className="mt-2 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
            {plural(t.not_in_master, 'material')} {t.not_in_master === 1 ? 'was' : 'were'} typed in the budget without picking {t.not_in_master === 1 ? 'it' : 'them'} from the item master, so the store cannot count {t.not_in_master === 1 ? 'it' : 'them'}. Pick the item on the BOQ line in Budgeting to link {t.not_in_master === 1 ? 'it' : 'them'}.
          </p>
        )}
        <div className="my-4">
          <Tabs label="Show" value={show} onChange={setShow} items={[
            { value: 'all', label: `All (${all.length})` },
            { value: 'arrange', label: `To arrange (${t?.to_arrange ?? 0})` },
            { value: 'over', label: `Issued past need (${t?.over_issued ?? 0})` },
            { value: 'free', label: `Not in item master (${t?.not_in_master ?? 0})` },
          ]} />
        </div>
        <DataTable label="Item sheet" rows={rows} columns={cols} rowKey={(r) => r.item_id ?? `free:${r.item_name}:${r.uom}`} loading={loading} onRowClick={setOpen}
          empty={show === 'all' ? 'No BOQ line has materials yet. Give each line its materials in Budgeting and they add up here.' : 'Nothing here.'} />
      </>)}
      {open && <LinesModal row={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

/** Where a material's need comes from: each BOQ line, how much one unit takes, and what has been issued to it. */
function LinesModal({ row, onClose }: { row: ItemSheetRow; onClose: () => void }) {
  const cols: TableColumn<ItemSheetLine>[] = [
    { id: 'line', header: 'BOQ line', cell: (l) => <div className="min-w-[10rem] max-w-[18rem]"><p>{l.item_no && <span className="font-medium">{l.item_no} </span>}{l.description}</p><p className="text-xs text-muted-foreground">{formatQty(l.boq_qty)} {l.boq_unit}</p></div> },
    { id: 'per', header: 'Per unit', align: 'right', cell: (l) => <div><p>{formatQty(l.per_unit, 4)} {l.budget_unit}</p>{l.wastage_percent > 0 && <p className="text-xs text-muted-foreground">+{l.wastage_percent}% wastage{l.wastage_source === 'STORE_NORM' ? ' (store norm)' : ''}</p>}</div> },
    { id: 'req', header: 'Required', align: 'right', cell: (l) => q(l.required, row.uom) },
    { id: 'iss', header: 'Issued to it', align: 'right', cell: (l) => <span className={l.issued > l.required ? 'font-semibold text-danger' : ''}>{q(l.issued, row.uom)}</span> },
  ]
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={row.item_name}
      description={`${formatQty(row.required)} ${row.uom} required${row.value ? `, ${formatINR(row.value)} in the budget` : ''}. Issued with no BOQ line named counts in the total only.`}>
      <DataTable label={`BOQ lines needing ${row.item_name}`} rows={row.lines} columns={cols} rowKey={(l) => l.key} empty="No BOQ line's budget asks for this - it was indented, ordered or issued on its own." />
    </Modal>
  )
}
