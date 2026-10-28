import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Download, Pencil } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, Field, NumField, Stat, StatGrid, Tabs, Textarea } from '@/components/ui'
import { budgetFileUrl, budgetKey, pct, saveBudgetSettings, useBudget, type Budget, type BudgetRow } from '@/api/budgeting'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { compactINR, formatINR } from '@/lib/utils'
import { plural } from '@/lib/format'
import { BudgetLineModal } from './BudgetLineModal'

type Show = 'all' | 'todo' | 'loss'

/** Our own cost for every line of the client's BOQ - material, labour and the rest - against what the BOQ pays, and the profit between them. */
export default function BudgetingPage() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const job = Number(params.get('job')) || 0
  const setJob = (id: number) => setParams((p) => { const q = new URLSearchParams(p); if (id) q.set('job', String(id)); else q.delete('job'); return q }, { replace: true })
  const [show, setShow] = useState<Show>('all')
  const [editing, setEditing] = useState<BudgetRow | null>(null)
  const q = useBudget(job)
  const b = q.data
  const t = b?.total
  const edit = can('workorders.manage')

  const rows = (b?.rows ?? []).filter((r) => (show === 'todo' ? !r.budgeted : show === 'loss' ? (r.profit ?? 0) < 0 && r.budgeted : true))
  const cols: TableColumn<BudgetRow>[] = [
    { id: 'no', header: 'Item', cell: (r) => r.item_no || '-', width: '4.5rem', sort: (r) => r.item_no },
    { id: 'what', header: 'Description', cell: (r) => <div className="min-w-[12rem] max-w-[26rem]"><p>{r.description}</p><p className="text-xs text-muted-foreground">{r.group_code}{r.group_code && ' · '}{r.quantity} {r.uom}</p></div>, sort: (r) => r.description },
    { id: 'rate', header: 'BOQ rate', align: 'right', cell: (r) => formatINR(r.rate), hideBelow: 'md', sort: (r) => r.rate },
    { id: 'rev', header: 'BOQ amount', align: 'right', cell: (r) => (r.rate_only ? 'Rate only' : formatINR(r.revenue)), sort: (r) => r.revenue },
    { id: 'cost', header: 'Our cost', align: 'right', cell: (r) => (r.budgeted ? <div><p>{formatINR(r.cost)}</p><p className="whitespace-nowrap text-xs text-muted-foreground">Mat {compactINR(r.material)} · Lab {compactINR(r.labour)} · Other {compactINR(r.other)}</p></div> : <Badge tone="warning">Not budgeted</Badge>), sort: (r) => r.cost },
    { id: 'profit', header: 'Profit', align: 'right', cell: (r) => (r.profit === null ? '-' : <span className={r.profit < 0 ? 'text-danger' : 'text-success'}>{formatINR(r.profit)}</span>), sort: (r) => r.profit ?? -Infinity },
    { id: 'margin', header: 'Margin', align: 'right', cell: (r) => (r.margin === null ? '-' : <span className={r.margin < 0 ? 'text-danger' : ''}>{pct(r.margin)}</span>), hideBelow: 'sm', sort: (r) => r.margin ?? -Infinity },
    ...(edit ? [{ id: 'edit', header: '', width: '3rem', cell: (r: BudgetRow) => <Pencil className="size-4 text-muted-foreground" aria-label={`Budget ${r.description}`} /> }] : []),
  ]

  return (
    <div>
      <PageHeader eyebrow="Projects" title="Budgeting" description="Price each line of the client's BOQ with our own cost - material, labour and the rest - and see the profit before the work is bought."
        actions={<Button variant="outline" disabled={!b?.boq} onClick={() => window.open(budgetFileUrl(job), '_blank')}><Download /> Excel</Button>} />
      <div className="mb-4 flex flex-wrap items-end gap-4"><ProjectPicker value={job} onChange={setJob} id="bud-job" /></div>
      {job > 0 && !q.isPending && !b?.boq && (
        <Card className="p-6 text-sm text-muted-foreground">This project has no BOQ yet. Add one under Clients &gt; BOQ and its lines will appear here to be priced.</Card>
      )}
      {(job === 0 || q.isPending || b?.boq) && (<>
        <StatGrid>
          <Stat label="BOQ value" value={compactINR(t?.boq_value)} sub={t ? `${plural(t.lines, 'line')}, ${t.lines_budgeted} budgeted` : undefined} loading={q.isPending && job > 0} />
          <Stat label="Material" value={compactINR(t?.material)} loading={q.isPending && job > 0} />
          <Stat label="Labour" value={compactINR(t?.labour)} loading={q.isPending && job > 0} />
          <Stat label="Plant & other" value={compactINR(t?.other)} loading={q.isPending && job > 0} />
          <Stat label="Overheads and contingency" value={compactINR((t?.overheads ?? 0) + (t?.contingency ?? 0))} loading={q.isPending && job > 0} />
          <Stat label="Our cost" value={compactINR(t?.cost)} loading={q.isPending && job > 0} />
          <Stat label="Profit" value={t && t.lines_budgeted ? compactINR(t.profit) : '-'} tone={t && t.lines_budgeted ? (t.profit < 0 ? 'danger' : 'success') : undefined}
            sub={t && t.margin !== null ? `${pct(t.margin)} on the budgeted lines` : 'Budget a line to see it'} loading={q.isPending && job > 0} />
          <Stat label="Whole BOQ at this margin" value={t?.projected_profit != null ? compactINR(t.projected_profit) : '-'}
            sub={t && t.unbudgeted_value > 0 ? `${compactINR(t.unbudgeted_value)} of BOQ still unbudgeted` : undefined} loading={q.isPending && job > 0} />
        </StatGrid>
        {b && edit && <Settings key={job + ':' + b.overhead_percent + ':' + b.contingency_percent} job={job} b={b} />}
        <div className="my-4 flex flex-wrap items-center justify-between gap-3">
          <Tabs label="Show" value={show} onChange={setShow} items={[
            { value: 'all', label: `All lines (${b?.rows.length ?? 0})` },
            { value: 'todo', label: `Not budgeted (${t ? t.lines - t.lines_budgeted : 0})` },
            { value: 'loss', label: `Losing money (${t?.losing ?? 0})` },
          ]} />
          {b && b.sections.length > 1 && <p className="text-xs text-muted-foreground">{b.sections.map((s) => `${s.group || 'Other'}: ${s.margin === null ? '-' : pct(s.margin)}`).join('  ·  ')}</p>}
        </div>
        <DataTable label="Budget by BOQ line" rows={rows} columns={cols} rowKey={(r) => r.key} loading={q.isPending && job > 0}
          empty={show === 'all' ? 'The BOQ has no priced lines.' : show === 'todo' ? 'Every line is budgeted.' : 'No budgeted line is losing money.'}
          onRowClick={edit ? setEditing : undefined} />
      </>)}
      {editing && b && <BudgetLineModal job={job} row={editing} overhead={b.overhead_percent} contingency={b.contingency_percent} onClose={() => setEditing(null)} />}
    </div>
  )
}

/** Overheads and contingency, as a share of the direct cost, and a note on what the budget assumes. */
function Settings({ job, b }: { job: number; b: Budget }) {
  const [oh, setOh] = useState(b.overhead_percent)
  const [ct, setCt] = useState(b.contingency_percent)
  const [note, setNote] = useState(b.note)
  const dirty = oh !== b.overhead_percent || ct !== b.contingency_percent || note !== b.note
  const save = useAction(() => saveBudgetSettings(job, { overhead_percent: oh, contingency_percent: ct, note }), { invalidate: [budgetKey(job)], success: 'Budget settings saved' })
  return (
    <Card className="mt-4 p-4">
      <div className="grid grid-cols-1 items-end gap-4 sm:grid-cols-[10rem_10rem_1fr_auto]">
        <Field label="Overheads %" hint="Site and office, on direct cost" htmlFor="bud-oh"><NumField id="bud-oh" value={oh} onValue={setOh} /></Field>
        <Field label="Contingency %" hint="Kept back for the unforeseen" htmlFor="bud-ct"><NumField id="bud-ct" value={ct} onValue={setCt} /></Field>
        <Field label="Assumptions" htmlFor="bud-note"><Textarea id="bud-note" rows={1} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Rates as of, what is excluded..." /></Field>
        <Button disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </div>
    </Card>
  )
}
