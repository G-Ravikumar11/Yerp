import { useState } from 'react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, ConfirmDialog, Field, Input, Modal, Select, Skeleton } from '@/components/ui'
import {
  plantKeys, resolveGap, reviewAlert, reviewFuelFlag, saveAlertSettings, useAlerts, useFuelMonitor, useMeterGaps, useMeterHistory, usePlantSettings, useProjectPlantCosts, useRentalVerification, verifyInvoice,
  type AlertRow, type FuelFlag, type MeterGap, type MonitorRow, type PlantCostRow, type RentalCheck,
} from '@/api/plant'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { LoadError, usePaged } from './plantParts'

const th = 'px-3 py-2 text-left text-xs font-medium text-muted-foreground'
const REVIEW = 'site.signoff|stores.manage|workorders.manage'
const FINANCE = 'accounts.manage|bills.pay'

// ---- meter gaps ----------------------------------------------------------------------------------

/** Days a machine went without a reading. Logging the missing days clears a gap; otherwise somebody says why it is there. */
export function MeterGaps({ assetId = 0 }: { assetId?: number }) {
  const { can } = useSession()
  const q = useMeterGaps(assetId)
  const [open, setOpen] = useState<MeterGap | null>(null)
  const done = useAction((v: { g: MeterGap; note: string }) => resolveGap({ asset_id: v.g.asset_id, from_date: v.g.from, to_date: v.g.to, note: v.note }), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: () => setOpen(null) })
  const gaps = q.data?.gaps ?? []
  const waiting = gaps.filter((g) => !g.resolved)
  if (!gaps.length) return null
  return (
    <section aria-label="Meter gaps" className="mb-3 rounded-lg border border-warning/40 p-3 text-[13px]">
      <h3 className="mb-1.5 font-semibold text-warning">Meter gaps: {waiting.length} to look at</h3>
      <ul className="grid gap-1">
        {gaps.slice(0, 12).map((g) => (
          <li key={`${g.asset_id}-${g.from}-${g.to}`} className="flex flex-wrap items-center gap-2">
            <span><strong>{g.code}</strong> {formatDate(g.from)} to {formatDate(g.to)}: {g.days_without_reading} {g.days_without_reading === 1 ? 'day' : 'days'} without a reading{g.unlogged_meter > 0 && `, ${g.unlogged_meter} ${g.unit} not logged`}</span>
            {g.resolved ? <span className="text-muted-foreground">Reviewed by {g.resolved_by}: {g.note}</span> : can(REVIEW) && <Button size="sm" variant="outline" onClick={() => setOpen(g)}>Review</Button>}
          </li>
        ))}
      </ul>
      <ConfirmDialog open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={open ? `Gap on ${open.code}` : ''} description="Say what was found. To fill the gap instead, log the missing days." reason={{ label: 'What was found', required: true }} confirmLabel="Save" cancelLabel="Cancel" loading={done.isPending} onConfirm={(note) => { if (open) done.mutate({ g: open, note: note ?? '' }) }} />
    </section>
  )
}

/** Every reading of a machine, every replacement and correction, oldest first, and who did each. */
export function MeterHistory({ id }: { id: number }) {
  const q = useMeterHistory(id)
  if (q.isError) return <LoadError message={q.error.message} retry={() => q.refetch()} />
  if (q.isPending || !q.data) return <Skeleton className="mb-5 h-24 w-full" />
  const rows = q.data.history
  return (
    <>
      <h3 className="mb-2 text-sm font-semibold">Meter history</h3>
      <MeterGaps assetId={id} />
      <div className="mb-5 max-h-96 overflow-auto rounded-lg border border-border">
        <table aria-label="Meter history" className="w-full min-w-[46rem] text-[13px]">
          <thead className="bg-surface"><tr><th className={th}>Date</th><th className={th}>Entry</th><th className={`${th} text-right`}>Opening / old</th><th className={`${th} text-right`}>Closing / new</th><th className={`${th} text-right`}>Hours</th><th className={th}>By</th><th className={th}>Note</th></tr></thead>
          <tbody>{rows.length ? rows.map((h, i) => (
            <tr key={i} className={`border-t border-border align-top ${h.type === 'Reading' ? '' : 'bg-warning-soft/40'}`}>
              <td className="whitespace-nowrap px-3 py-2">{formatDate(h.date)}{h.shift && <div className="text-xs text-muted-foreground">{h.shift}</div>}</td>
              <td className="px-3 py-2">{h.type}{h.status && h.status !== 'Approved' && <div className="text-xs text-muted-foreground">{h.status}</div>}</td>
              <td className="px-3 py-2 text-right tabular">{h.opening ?? '-'}</td>
              <td className="px-3 py-2 text-right tabular">{h.closing ?? '-'}</td>
              <td className="px-3 py-2 text-right tabular">{h.hours ?? ''}</td>
              <td className="px-3 py-2">{h.by || '-'}{h.approved_by && <div className="text-xs text-muted-foreground">Approved by {h.approved_by}</div>}</td>
              <td className="px-3 py-2">{h.note}</td>
            </tr>
          )) : <tr><td colSpan={7} className="px-3 py-4 text-center text-muted-foreground">No readings logged.</td></tr>}</tbody>
        </table>
      </div>
    </>
  )
}

// ---- fuel ----------------------------------------------------------------------------------------

const FLAG_TONE: Record<string, 'danger' | 'warning' | 'success' | 'neutral'> = { Open: 'danger', 'Under review': 'warning', Resolved: 'success', Dismissed: 'neutral' }
const DECISION_LABEL = { investigate: 'Under review', resolve: 'Resolve', dismiss: 'Dismiss' }

/** Consumption against the norm, machine by machine, and the fills that do not add up. A flag is a question to look into, not a finding. */
export function FuelMonitor({ from, to, asset }: { from: string; to: string; asset: number }) {
  const { can } = useSession()
  const q = useFuelMonitor({ date_from: from, date_to: to, asset_id: asset })
  const [open, setOpen] = useState<{ f: FuelFlag; decision: keyof typeof DECISION_LABEL } | null>(null)
  const act = useAction((v: { f: FuelFlag; decision: string; note: string }) => reviewFuelFlag({ fuel_id: v.f.fuel_id, reason: v.f.reason, decision: v.decision, note: v.note }), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: () => setOpen(null) })
  const flags = usePaged(q.data?.flags, 10)
  if (q.isError) return <LoadError message={q.error.message} retry={() => q.refetch()} />
  const d = q.data
  const machines: TableColumn<MonitorRow>[] = [
    { id: 'm', header: 'Machine', cell: (m) => <div><span className="font-mono text-[13px]">{m.code}</span> {m.name}</div> },
    { id: 'l', header: 'Litres', align: 'right', sort: (m) => m.litres, cell: (m) => m.litres },
    { id: 'h', header: 'Hours', align: 'right', cell: (m) => m.operating_hours },
    { id: 'a', header: 'Actual L/h', align: 'right', cell: (m) => <span className={m.over_norm ? 'font-semibold text-danger' : ''}>{m.operating_hours ? m.actual_lph : '-'}</span> },
    { id: 'n', header: 'Norm L/h', align: 'right', cell: (m) => m.fuel_norm_lph ?? <span className="text-muted-foreground">Not set</span> },
    { id: 'e', header: 'Expected L', align: 'right', hideBelow: 'md', cell: (m) => (m.fuel_norm_lph ? m.expected_litres : '-') },
    { id: 't', header: 'Tank L', align: 'right', hideBelow: 'md', cell: (m) => m.tank_capacity_l ?? <span className="text-muted-foreground">Not set</span> },
    { id: 'f', header: 'Open flags', align: 'right', cell: (m) => (m.open_flags ? <Badge tone="danger" dot>{m.open_flags}</Badge> : '-') },
  ]
  const cols: TableColumn<FuelFlag>[] = [
    { id: 'd', header: 'Date', sort: (f) => f.date, cell: (f) => <div>{formatDate(f.date)}<div className="font-mono text-xs text-muted-foreground">{f.number}</div></div> },
    { id: 'm', header: 'Machine', cell: (f) => <div><span className="font-mono text-[13px]">{f.code}</span> {f.machine}<div className="text-xs text-muted-foreground">{f.project}</div></div> },
    { id: 'q', header: 'Litres', align: 'right', cell: (f) => f.litres },
    { id: 'r', header: 'Reason', cell: (f) => <div><strong>{f.label}</strong><div className="text-xs text-muted-foreground">{f.detail}</div></div> },
    { id: 's', header: 'Status', cell: (f) => <div><Badge tone={FLAG_TONE[f.status] ?? 'neutral'} dot>{f.status}</Badge>{f.note && <div className="mt-0.5 text-xs text-muted-foreground">{f.note} - {f.reviewed_by}</div>}</div> },
    {
      id: 'act', header: '', align: 'right',
      cell: (f) => can(REVIEW) && !['Resolved', 'Dismissed'].includes(f.status) ? (
        <div className="flex flex-wrap justify-end gap-1">
          {f.status === 'Open' && <Button size="sm" variant="outline" onClick={() => setOpen({ f, decision: 'investigate' })}>Investigate</Button>}
          <Button size="sm" variant="outline" onClick={() => setOpen({ f, decision: 'resolve' })}>Resolve</Button>
          <Button size="sm" variant="ghost" onClick={() => setOpen({ f, decision: 'dismiss' })}>Dismiss</Button>
        </div>
      ) : null,
    },
  ]
  return (
    <section aria-label="Fuel monitoring" className="mb-4">
      <h3 className="mb-2 text-sm font-semibold">Fuel monitoring{d ? ` (${d.tolerance_percent}% over the norm is flagged)` : ''}</h3>
      <Card className="mb-3 overflow-hidden"><DataTable label="Fuel by machine" className="rounded-none border-0 shadow-none" rows={d?.machines ?? []} columns={machines} rowKey={(m) => m.asset_id} loading={q.isPending} empty="No fuel, and no machine with a norm or tank set." /></Card>
      {(d?.flags.length ?? 0) > 0 && <Card className="overflow-hidden"><DataTable label="Fuel flags" className="rounded-none border-0 shadow-none" rows={flags.shown} columns={cols} rowKey={(f) => `${f.fuel_id}-${f.reason}`} empty="" />{flags.pager}</Card>}
      <ConfirmDialog open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={open ? `${DECISION_LABEL[open.decision]}: ${open.f.number}` : ''} description={open?.f.detail} reason={{ label: 'Reason', required: true }} confirmLabel="Save" cancelLabel="Cancel" loading={act.isPending} onConfirm={(note) => { if (open) act.mutate({ f: open.f, decision: open.decision, note: note ?? '' }) }} />
    </section>
  )
}

// ---- rental bills --------------------------------------------------------------------------------

const BILL_TONE: Record<string, 'danger' | 'warning' | 'success' | 'neutral'> = { Matched: 'success', Mismatch: 'danger', Duplicate: 'danger', Missing: 'danger', Incomplete: 'warning', 'In progress': 'neutral' }
const money = (v: number | null) => (v === null ? '-' : formatINR(v))

/** Each bill beside what its agreement comes to, and the months with no bill. Actual amounts are never changed here. */
export function RentalVerification() {
  const { can } = useSession()
  const [month, setMonth] = useState('')
  const q = useRentalVerification(month)
  const [open, setOpen] = useState<{ r: RentalCheck; decision: 'approve' | 'dispute' } | null>(null)
  const act = useAction((v: { id: number; decision: string; note: string }) => verifyInvoice(v.id, v.decision, v.note), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: () => setOpen(null) })
  const { shown, pager } = usePaged(q.data?.rows, 10)
  const s = q.data?.summary
  const cols: TableColumn<RentalCheck>[] = [
    { id: 'mo', header: 'Month', sort: (r) => r.month, cell: (r) => <div>{r.month}<div className="text-xs text-muted-foreground">{r.invoice_no || 'No invoice'}</div></div> },
    { id: 'm', header: 'Machine', cell: (r) => <div><span className="font-mono text-[13px]">{r.code}</span> {r.machine}<div className="text-xs text-muted-foreground">{[r.supplier, r.project].filter(Boolean).join(' - ')}</div></div> },
    { id: 'h', header: 'Hours', align: 'right', hideBelow: 'md', cell: (r) => <div>{r.actual_hours} of {r.minimum_hours} min<div className="text-xs text-muted-foreground">{r.overtime_hours} OT at {formatINR(r.overtime_rate)}</div></div> },
    { id: 'rt', header: 'Rate', align: 'right', hideBelow: 'lg', cell: (r) => <div>{formatINR(r.rate)}<div className="text-xs text-muted-foreground">{r.billing}</div></div> },
    { id: 'e', header: 'Expected', align: 'right', cell: (r) => formatINR(r.expected) },
    { id: 'a', header: 'Invoice', align: 'right', cell: (r) => money(r.actual) },
    { id: 'df', header: 'Difference', align: 'right', cell: (r) => <span className={r.status === 'Mismatch' ? 'font-semibold text-danger' : ''}>{money(r.difference)}</span> },
    { id: 's', header: 'Status', cell: (r) => <div><Badge tone={BILL_TONE[r.status] ?? 'neutral'} dot>{r.status}</Badge>{r.detail && <div className="mt-0.5 text-xs text-muted-foreground">{r.detail}</div>}{r.verification_status && <div className="mt-0.5 text-xs">{r.verification_status} by {r.verified_by}{r.verification_note && `: ${r.verification_note}`}</div>}</div> },
    {
      id: 'act', header: '', align: 'right',
      cell: (r) => r.invoice_id && can(FINANCE) && !r.verification_status && r.status !== 'Matched' ? (
        <div className="flex flex-wrap justify-end gap-1">
          <Button size="sm" variant="outline" onClick={() => setOpen({ r, decision: 'approve' })}>Approve</Button>
          <Button size="sm" variant="ghost" className="text-danger" onClick={() => setOpen({ r, decision: 'dispute' })}>Dispute</Button>
        </div>
      ) : null,
    },
  ]
  return (
    <section aria-label="Rental bill verification" className="mt-5">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold">Rental bill verification</h3>
        <Input type="month" aria-label="Billing month" className="w-40" value={month} onChange={(e) => setMonth(e.target.value)} />
        {s && <span className="text-[13px] text-muted-foreground">{s.Mismatch} differ - {s.Duplicate} duplicate - {s.Missing + s.Incomplete} unbilled - {q.data?.tolerance_percent}% tolerance</span>}
      </div>
      {q.isError ? <LoadError message={q.error.message} retry={() => q.refetch()} /> : <Card className="overflow-hidden"><DataTable label="Rental bills" className="rounded-none border-0 shadow-none" rows={shown} columns={cols} rowKey={(r) => `${r.rental_id}-${r.invoice_id ?? r.month}`} loading={q.isPending} empty="No hire to check for this month." />{pager}</Card>}
      <p className="mt-2 text-[11px] text-muted-foreground">Expected follows each agreement&apos;s billing cycle, with its minimum hours per cycle. The invoice amount is kept as billed.</p>
      <ConfirmDialog open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={open ? `${open.decision === 'approve' ? 'Approve' : 'Dispute'} invoice ${open.r.invoice_no}?` : ''} description={open ? `Billed ${money(open.r.actual)}, expected ${formatINR(open.r.expected)}.` : ''} reason={{ label: open?.decision === 'dispute' ? 'What is wrong with it' : 'Note', required: open?.decision === 'dispute' }} confirmLabel={open?.decision === 'approve' ? 'Approve' : 'Dispute'} cancelLabel="Cancel" loading={act.isPending} onConfirm={(note) => { if (open && open.r.invoice_id) act.mutate({ id: open.r.invoice_id, decision: open.decision, note: note ?? '' }) }} />
    </section>
  )
}

// ---- alerts --------------------------------------------------------------------------------------

const KIND_LABEL: Record<string, string> = { weekly: 'Weekly', emergency: 'Emergency', unbilled: 'Unbilled rental' }
const ALERT_TONE: Record<string, 'danger' | 'warning' | 'success'> = { Open: 'danger', Reviewed: 'warning', Resolved: 'success' }

export function PlantAlerts() {
  const { can } = useSession()
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const q = useAlerts(kind, status)
  const [open, setOpen] = useState<{ a: AlertRow; status: 'Reviewed' | 'Resolved' } | null>(null)
  const [settings, setSettings] = useState(false)
  const act = useAction((v: { id: number; status: string; note: string }) => reviewAlert(v.id, v.status, v.note), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: () => setOpen(null) })
  const { shown, pager } = usePaged(q.data?.alerts)
  const cols: TableColumn<AlertRow>[] = [
    { id: 'w', header: 'Raised', sort: (a) => a.created_at, cell: (a) => <div>{formatDate(a.created_at.slice(0, 10))}<div className="text-xs text-muted-foreground">{KIND_LABEL[a.kind] ?? a.kind} - {a.period}</div></div> },
    { id: 'm', header: 'Alert', cell: (a) => <div><strong>{a.title}</strong><div className="whitespace-pre-line text-xs text-muted-foreground">{a.body}</div></div> },
    { id: 'd', header: 'Delivery', hideBelow: 'md', cell: (a) => <div><Badge tone={a.delivery_status === 'Delivered' ? 'success' : 'danger'} dot>{a.delivery_status}</Badge><div className="text-xs text-muted-foreground">{a.sent_to || 'Bell only'}</div></div> },
    { id: 's', header: 'Status', cell: (a) => <div><Badge tone={ALERT_TONE[a.status] ?? 'warning'} dot>{a.status}</Badge>{a.reviewed_by && <div className="mt-0.5 text-xs text-muted-foreground">{a.reviewed_by}{a.review_note && `: ${a.review_note}`}</div>}</div> },
    {
      id: 'act', header: '', align: 'right',
      cell: (a) => can(`${REVIEW}|${FINANCE}`) && a.status !== 'Resolved' ? (
        <div className="flex flex-wrap justify-end gap-1">
          {a.status === 'Open' && <Button size="sm" variant="outline" onClick={() => setOpen({ a, status: 'Reviewed' })}>Reviewed</Button>}
          <Button size="sm" variant="outline" onClick={() => setOpen({ a, status: 'Resolved' })}>Resolved</Button>
        </div>
      ) : null,
    },
  ]
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-44"><Select aria-label="Kind of alert" value={kind} placeholder="Every kind" onChange={(e) => setKind(e.target.value)} options={Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))} /></div>
        <div className="w-36"><Select aria-label="Alert status" value={status} placeholder="Any status" onChange={(e) => setStatus(e.target.value)} options={['Open', 'Reviewed', 'Resolved'].map((s) => ({ value: s, label: s }))} /></div>
        {q.data && <span className="text-[13px] text-muted-foreground">{q.data.open} open</span>}
        {can('stores.manage|workorders.manage') && <Button className="ml-auto" variant="outline" onClick={() => setSettings(true)}>Alert settings</Button>}
      </div>
      <p className="mb-2 text-[13px] text-muted-foreground">Checked once a week per machine, once a month for unbilled hire. Emergency breakdowns are sent as soon as they are reported.</p>
      {q.isError ? <LoadError message={q.error.message} retry={() => q.refetch()} /> : <Card className="overflow-hidden"><DataTable label="Plant alerts" className="rounded-none border-0 shadow-none" rows={shown} columns={cols} rowKey={(a) => a.id} loading={q.isPending} empty="No plant alerts." />{!q.isPending && pager}</Card>}
      <ConfirmDialog open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={open?.a.title ?? ''} description={`Mark it ${open?.status.toLowerCase()}.`} reason={{ label: 'Note', required: false }} confirmLabel="Save" cancelLabel="Cancel" loading={act.isPending} onConfirm={(note) => { if (open) act.mutate({ id: open.a.id, status: open.status, note: note ?? '' }) }} />
      {settings && <AlertSettings onClose={() => setSettings(false)} />}
    </div>
  )
}

function AlertSettings({ onClose }: { onClose: () => void }) {
  const q = usePlantSettings()
  const [f, setF] = useState<{ document_alert_days?: string; fuel_tolerance_percent?: string; rental_tolerance_percent?: string }>({})
  const value = (k: keyof typeof f) => f[k] ?? String(q.data?.[k] ?? '')
  const save = useAction(() => saveAlertSettings({ document_alert_days: Number(value('document_alert_days')), fuel_tolerance_percent: Number(value('fuel_tolerance_percent')), rental_tolerance_percent: Number(value('rental_tolerance_percent')) }), { invalidate: [plantKeys.all], success: (x) => x.message, onSuccess: onClose })
  const field = (k: keyof typeof f, label: string, hint: string) => <Field label={label} htmlFor={`as-${k}`} hint={hint}><Input id={`as-${k}`} type="number" min="0" value={value(k)} onChange={(e) => setF((x) => ({ ...x, [k]: e.target.value }))} /></Field>
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Alert settings" footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button></>}>
      {q.isPending ? <Skeleton className="h-32 w-full" /> : (
        <div className="grid gap-4">
          {field('document_alert_days', 'Warn before insurance or fitness runs out (days)', 'Between 1 and 365')}
          {field('fuel_tolerance_percent', 'Fuel tolerance over the norm (%)', 'Above this a fill is flagged')}
          {field('rental_tolerance_percent', 'Rental bill tolerance (%)', 'A bill further than this from the agreement is flagged')}
          {save.error && <p role="alert" className="text-[13px] text-danger">{save.error.message}</p>}
        </div>
      )}
    </Modal>
  )
}

// ---- project costs -------------------------------------------------------------------------------

const CATEGORY_LABEL: Record<string, string> = { fuel: 'Fuel', rental: 'Rental', hire: 'Hire', maintenance: 'Maintenance', expenses: 'Plant expenses' }

/** What the machines cost each project, and the record behind every figure. */
export function ProjectPlantCosts() {
  const q = useProjectPlantCosts()
  const [open, setOpen] = useState<PlantCostRow | null>(null)
  if (q.isError) return <LoadError message={q.error.message} retry={() => q.refetch()} />
  const cols: TableColumn<PlantCostRow>[] = [
    { id: 'p', header: 'Project', cell: (r) => <button type="button" className="text-left font-medium text-primary hover:underline" onClick={() => setOpen(r)}>{r.project}</button> },
    { id: 'f', header: 'Fuel', align: 'right', cell: (r) => formatINR(r.fuel) },
    { id: 'r', header: 'Rental', align: 'right', cell: (r) => formatINR(r.rental + r.hire) },
    { id: 'm', header: 'Maintenance', align: 'right', hideBelow: 'md', cell: (r) => formatINR(r.maintenance) },
    { id: 'e', header: 'Plant expenses', align: 'right', hideBelow: 'md', cell: (r) => formatINR(r.expenses) },
    { id: 't', header: 'Total plant cost', align: 'right', sort: (r) => r.total, cell: (r) => <strong>{formatINR(r.total)}</strong> },
  ]
  return (
    <section aria-label="Plant cost by project" className="mt-6">
      <h2 className="mb-2 text-sm font-semibold">Plant cost by project</h2>
      <Card className="overflow-hidden"><DataTable label="Plant cost by project" className="rounded-none border-0 shadow-none" rows={q.data?.projects ?? []} columns={cols} rowKey={(r) => r.job_id} loading={q.isPending} empty="No plant costs recorded." /></Card>
      <Modal open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={open ? `Plant cost: ${open.project}` : ''} description={open ? `${formatINR(open.total)} in all${open.duplicates_excluded ? `; ${formatINR(open.duplicates_excluded)} left out as already counted` : ''}${open.unbilled_hire_estimate ? `; about ${formatINR(open.unbilled_hire_estimate)} of hire not billed yet, not in the total` : ''}.` : ''} footer={<Button variant="ghost" onClick={() => setOpen(null)}>Close</Button>}>
        <div className="max-h-[60vh] overflow-auto rounded-lg border border-border">
          <table aria-label="Plant cost lines" className="w-full min-w-[40rem] text-[13px]">
            <thead className="bg-surface"><tr><th className={th}>Date</th><th className={th}>Kind</th><th className={th}>Source</th><th className={th}>Machine</th><th className={th}>Detail</th><th className={`${th} text-right`}>Amount</th></tr></thead>
            <tbody>{open?.lines.map((l, i) => (
              <tr key={i} className="border-t border-border align-top">
                <td className="whitespace-nowrap px-3 py-2">{formatDate(l.date)}</td>
                <td className="px-3 py-2">{CATEGORY_LABEL[l.category] ?? l.category}</td>
                <td className="px-3 py-2">{l.source}<div className="font-mono text-xs text-muted-foreground">{l.ref}</div></td>
                <td className="px-3 py-2">{l.code}</td>
                <td className="px-3 py-2">{l.description}</td>
                <td className="px-3 py-2 text-right tabular">{formatINR(l.amount)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Modal>
    </section>
  )
}
