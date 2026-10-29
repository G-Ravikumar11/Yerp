import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, FileSpreadsheet, Plus, Printer } from 'lucide-react'
import { Badge, Button, Field, Input, Modal, Select, Skeleton, Textarea } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storePerm, storePost } from '@/api/store'
import { StorePicker } from '../shared'
import { dmy, num, outwardKeys, qs, today, useDoc, useDocs, useGatePass, useGatePasses, type Doc, type GatePass } from './api'

const TONE = { ISSUED: 'warning', CLOSED: 'success', CANCELLED: 'danger' } as const
const LABEL = { ISSUED: 'Out', CLOSED: 'Material back', CANCELLED: 'Cancelled' } as const

/** Gate passes: material that has left, or is leaving, the store's premises. */
export function GatePassListPage() {
  const nav = useNavigate()
  const { can } = useSession()
  const [f, setF] = useState({ status: '', store_id: 0, q: '' })
  const list = useGatePasses(f)
  const columns: TableColumn<GatePass>[] = [
    { id: 'no', header: 'Number', width: '14rem', sort: (g) => g.number, cell: (g) => <Link className="font-mono text-[13px] font-medium text-primary hover:underline" to={`/store/hub/outward/gate-pass/${g.id}`}>{g.number}</Link> },
    { id: 'date', header: 'Date', width: '8rem', sort: (g) => g.date, cell: (g) => dmy(g.date) },
    { id: 'iss', header: 'Issue', width: '14rem', hideBelow: 'md', cell: (g) => g.issue_number },
    { id: 'to', header: 'Going to', hideBelow: 'sm', cell: (g) => g.destination },
    { id: 'veh', header: 'Vehicle', width: '9rem', hideBelow: 'lg', cell: (g) => g.vehicle_no || '-' },
    { id: 'due', header: 'Due back', width: '10rem', hideBelow: 'md', cell: (g) => (g.returnable ? <span className={g.overdue_days ? 'text-danger' : ''}>{dmy(g.expected_return_date)}{g.overdue_days > 0 && ` (${g.overdue_days} days late)`}</span> : <span className="text-muted-foreground">Not returnable</span>) },
    { id: 'st', header: 'Status', width: '9rem', cell: (g) => <Badge tone={TONE[g.status]} dot>{LABEL[g.status]}</Badge> },
  ]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Store" htmlFor="gp-store" className="w-52"><StorePicker id="gp-store" value={f.store_id || null} placeholder="All my stores" onChange={(id) => setF({ ...f, store_id: id ?? 0 })} /></Field>
        <Field label="Status" htmlFor="gp-status" className="w-44"><Select id="gp-status" value={f.status} placeholder="Any" onChange={(e) => setF({ ...f, status: e.target.value })} options={Object.entries(LABEL).map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label="Search" htmlFor="gp-q" className="w-44"><Input id="gp-q" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} placeholder="Number, vehicle, place" /></Field>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" asChild><a href={`/api/store/outward/gate-pass/export${qs(f)}`}><FileSpreadsheet /> Excel</a></Button>
          {can(storePerm('outward', 'create')) && <Button onClick={() => nav('/store/hub/outward/gate-pass/new')}><Plus /> New gate pass</Button>}
        </div>
      </div>
      {list.isError ? <p role="alert" className="text-sm text-danger">Could not load the gate passes.</p> : <DataTable label="Gate passes" rows={list.data?.items ?? []} loading={list.isPending} columns={columns} rowKey={(g) => g.id} onRowClick={(g) => nav(`/store/hub/outward/gate-pass/${g.id}`)} empty="No gate passes yet." />}
    </div>
  )
}

/** A pass for material leaving the premises, made from a posted issue: all of it, or the quantities given. */
export function GatePassForm() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const issues = useDocs('issue', { status: 'POSTED', store_id: 0, q: '' })
  const [issueId, setIssueId] = useState(Number(params.get('issue') || 0))
  const [f, setF] = useState({ gate_date: today(), vehicle_no: '', driver_name: '', destination: '', purpose: '', expected_return_date: '', remarks: '' })
  const [qty, setQty] = useState<Record<number, string>>({})
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const full = useDoc('issue', issueId).data?.lines
  const picked = (full ?? []).filter((l) => Number(qty[l.id]) > 0)
  const save = useAction(() => storePost<GatePass>('outward', '/gate-pass', { ...f, issue_id: issueId, lines: picked.map((l) => ({ issue_line_id: l.id, qty: qty[l.id], uom: l.base_uom })) }),
    { invalidate: [[...outwardKeys.all]], success: (g) => `Gate pass ${g.number} made`, onSuccess: (g) => nav(`/store/hub/outward/gate-pass/${g.id}`) })
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (issueId && f.destination.trim()) save.mutate() }} className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Issue" htmlFor="gf-issue" hint="Only posted issues."><Select id="gf-issue" value={issueId || ''} placeholder="Choose an issue" onChange={(e) => { setIssueId(Number(e.target.value) || 0); setQty({}) }} options={(issues.data?.items ?? []).map((i) => ({ value: i.id, label: `${i.number} - ${i.received_by_name || i.holder_name || i.project}` }))} /></Field>
        <Field label="Date" htmlFor="gf-date"><Input id="gf-date" type="date" max={today()} value={f.gate_date} onChange={(e) => set('gate_date', e.target.value)} /></Field>
        <Field label="Going to" htmlFor="gf-dest"><Input id="gf-dest" value={f.destination} onChange={(e) => set('destination', e.target.value)} placeholder="Site, yard or party" maxLength={200} /></Field>
        <Field label="Vehicle no." htmlFor="gf-veh"><Input id="gf-veh" value={f.vehicle_no} onChange={(e) => set('vehicle_no', e.target.value)} /></Field>
        <Field label="Driver" htmlFor="gf-drv"><Input id="gf-drv" value={f.driver_name} onChange={(e) => set('driver_name', e.target.value)} /></Field>
        <Field label="Due back" htmlFor="gf-due" hint="For returnable items; taken from the issue when left empty."><Input id="gf-due" type="date" min={f.gate_date} value={f.expected_return_date} onChange={(e) => set('expected_return_date', e.target.value)} /></Field>
        <Field label="Purpose" htmlFor="gf-purpose"><Input id="gf-purpose" value={f.purpose} onChange={(e) => set('purpose', e.target.value)} /></Field>
        <Field label="Remarks" htmlFor="gf-rem" className="sm:col-span-2"><Textarea id="gf-rem" rows={1} value={f.remarks} onChange={(e) => set('remarks', e.target.value)} /></Field>
      </div>
      {issueId > 0 && (
        <section aria-labelledby="gf-lines">
          <h3 id="gf-lines" className="mb-2 border-b pb-1 text-sm font-semibold">What is leaving</h3>
          <p className="mb-2 text-xs text-muted-foreground">Leave every quantity empty to send everything on the issue.</p>
          <ul className="divide-y rounded-lg border">
            {(full ?? []).map((l) => (
              <li key={l.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-sm">
                <span><span className="font-medium">{l.item_name}</span> <span className="text-muted-foreground">issued {num(l.qty)} {l.base_uom}</span></span>
                <span className="flex items-center gap-2"><Input aria-label={`Quantity of ${l.item_name} leaving`} inputMode="decimal" className="h-9 w-28 text-right" placeholder="All" value={qty[l.id] ?? ''} onChange={(e) => setQty((q) => ({ ...q, [l.id]: e.target.value }))} /> {l.base_uom}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button type="button" variant="ghost" onClick={() => nav('/store/hub/outward/gate-pass')}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!issueId || !f.destination.trim()}>Make the gate pass</Button>
      </div>
    </form>
  )
}

/** One gate pass: where it is going, what, and when it is due back; closed when the material is back, or cancelled. */
export function GatePassPage() {
  const { id } = useParams()
  const { can } = useSession()
  const q = useGatePass(Number(id))
  const [cancelling, setCancelling] = useState(false)
  const [why, setWhy] = useState('')
  const refresh = [[...outwardKeys.all]]
  const close = useAction(() => storePost<GatePass>('outward', `/gate-pass/${id}/close`), { invalidate: refresh, success: 'Marked as returned' })
  const cancel = useAction(() => storePost<GatePass>('outward', `/gate-pass/${id}/cancel`, { reason: why }), { invalidate: refresh, success: 'Gate pass cancelled', onSuccess: () => { setCancelling(false); setWhy('') } })
  const back = <Link to="/store/hub/outward/gate-pass" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Gate passes</Link>
  const g = q.data
  if (q.isPending) return <div>{back}<Skeleton className="h-40 w-full" /></div>
  if (q.isError || !g) return <div>{back}<p role="alert" className="text-sm text-danger">Could not load this gate pass.</p></div>
  const facts: [string, string][] = [['Store', g.store_code], ['Date', dmy(g.date)], ['Against issue', g.issue_number], ['Going to', g.destination], ['Vehicle', g.vehicle_no || '-'], ['Driver', g.driver_name || '-'], ['Received by', g.received_by || '-'],
    ['Authorised by', g.authorised_by], ['Purpose', g.purpose || '-'], ...(g.returnable ? ([['Due back', dmy(g.expected_return_date)]] as [string, string][]) : []), ['Remarks', g.remarks || '-']]
  return (
    <div>
      {back}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="font-mono text-lg font-semibold">{g.number}</h2><div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground"><Badge tone={TONE[g.status]} dot>{LABEL[g.status]}</Badge> {g.returnable ? 'Returnable gate pass' : 'Outward gate pass'}{g.overdue_days > 0 && <Badge tone="danger">{g.overdue_days} days overdue</Badge>}</div></div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild><a href={`/api/store/outward/gate-pass/${g.id}/print`} target="_blank" rel="noreferrer"><Printer /> Print</a></Button>
          {g.status === 'ISSUED' && g.returnable && can(storePerm('outward', 'create')) && <Button loading={close.isPending} onClick={() => close.mutate()}>Material is back</Button>}
          {g.status === 'ISSUED' && can(storePerm('outward', 'cancel')) && <Button variant="outline" onClick={() => setCancelling(true)}>Cancel</Button>}
        </div>
      </div>
      {g.status === 'CANCELLED' && <p role="status" className="mb-4 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">Cancelled: {g.cancel_reason}.</p>}
      <dl className="mb-5 grid gap-x-6 gap-y-2 rounded-xl border border-border bg-card p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">{facts.map(([k, v]) => <div key={k}><dt className="text-xs uppercase tracking-wide text-muted-foreground">{k}</dt><dd className="font-medium">{v}</dd></div>)}</dl>
      <DataTable label="Gate pass lines" rows={g.lines ?? []} rowKey={(l) => l.id} columns={[
        { id: 'item', header: 'Item', cell: (l) => <div><div className="font-medium">{l.item_name}</div><div className="font-mono text-xs text-muted-foreground">{l.item_code}</div></div> },
        { id: 'qty', header: 'Quantity', align: 'right', width: '10rem', cell: (l) => `${num(l.qty)} ${l.base_uom}` },
      ]} />
      <Modal open={cancelling} onOpenChange={setCancelling} title="Cancel this gate pass?" description="Use this if the material did not leave.">
        <form onSubmit={(e) => { e.preventDefault(); if (why.trim().length > 2) cancel.mutate() }} className="grid gap-4">
          <Field label="Why" htmlFor="gp-why"><Input id="gp-why" value={why} onChange={(e) => setWhy(e.target.value)} autoFocus maxLength={200} /></Field>
          <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setCancelling(false)}>Keep it</Button><Button type="submit" loading={cancel.isPending} disabled={why.trim().length < 3}>Cancel it</Button></div>
        </form>
      </Modal>
    </div>
  )
}

export type { Doc }
