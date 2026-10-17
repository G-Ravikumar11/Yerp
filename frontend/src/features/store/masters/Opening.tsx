import { useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { FileSpreadsheet, FileText, Plus, Trash2, Upload } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, Field, Input, Select, Textarea } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { storeKeys, storePerm, type StoreItemOption } from '@/api/store'
import { DocActionsBar, DocStatusBadge, ItemPicker, StorePicker, UomQtyInput, type DocAction } from '../shared'
import {
  createOpening, importSheet, mastersKeys, OPENING_TEMPLATE, openingAction, openingPdf, previewSheet, updateOpening, useBins, useOpening,
  useOpenings, type Opening, type OpeningLineInput, type Preview,
} from './api'

export const BASE = '/store/hub/masters'
const refresh = { invalidate: [mastersKeys.all, storeKeys.all] }
const SOURCE: Record<Opening['source'], string> = { MANUAL: 'Typed', CSV: 'From a sheet', LEGACY: 'Carried over' }
const money = (s: string | undefined) => formatINR(Number(s ?? 0))

/** Masters > Opening stock: every opening, newest first. */
export function OpeningList() {
  const { can } = useSession()
  const [storeId, setStoreId] = useState<number | null>(null)
  const [status, setStatus] = useState('')
  const list = useOpenings(storeId ?? 0, status)
  const nav = useNavigate()
  const cols: TableColumn<Opening>[] = [
    { id: 'no', header: 'Number', sort: (o) => o.number, cell: (o) => <span className="font-mono font-semibold">{o.number}</span> },
    { id: 'store', header: 'Store', cell: (o) => `${o.store_code} - ${o.store_name}`, hideBelow: 'md' },
    { id: 'date', header: 'As on', sort: (o) => o.opening_date, cell: (o) => formatDate(o.opening_date) },
    { id: 'lines', header: 'Items', align: 'right', width: '5rem', cell: (o) => o.lines_count, hideBelow: 'md' },
    { id: 'value', header: 'Value', align: 'right', sort: (o) => Number(o.total_value), cell: (o) => <strong>{money(o.total_value)}</strong> },
    { id: 'src', header: 'Source', width: '8rem', hideBelow: 'lg', cell: (o) => SOURCE[o.source] },
    { id: 'st', header: 'Status', width: '8rem', cell: (o) => <DocStatusBadge status={o.status} /> },
  ]
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-64"><StorePicker value={storeId} onChange={(id) => setStoreId(id)} placeholder="All my stores" /></div>
        <div className="w-40">
          <Select aria-label="Status" value={status} options={[{ value: '', label: 'Any status' }, ...['DRAFT', 'SUBMITTED', 'APPROVED', 'POSTED', 'CANCELLED'].map((s) => ({ value: s, label: s[0] + s.slice(1).toLowerCase() }))]} onChange={(e) => setStatus(e.target.value)} />
        </div>
        {can(storePerm('masters', 'create')) && (
          <div className="ml-auto flex gap-2">
            <Button variant="outline" asChild><Link to={`${BASE}/opening/import`}><Upload /> Import a sheet</Link></Button>
            <Button asChild><Link to={`${BASE}/opening/new`}><Plus /> New opening</Link></Button>
          </div>
        )}
      </div>
      <DataTable label="Opening stock" rows={list.data ?? []} columns={cols} rowKey={(o) => o.id} loading={list.isPending} onRowClick={(o) => nav(`${BASE}/opening/${o.id}`)} empty="No opening stock yet. Enter what each store held on the day it starts on the Store module." />
    </div>
  )
}

interface Line { key: number; item: StoreItemOption | null; qty: { qty: string; uom: string }; rate: string; bin_id: number | null; remarks: string }
let lineKey = 0
const emptyLine = (): Line => ({ key: ++lineKey, item: null, qty: { qty: '', uom: '' }, rate: '', bin_id: null, remarks: '' })

/** A new opening, or a draft being changed. */
export function OpeningForm() {
  const { id } = useParams()
  const existing = useOpening(Number(id) || 0)
  if (id && !existing.data) return <p className="text-sm text-muted-foreground">Loading...</p>
  return <OpeningEditor key={existing.data?.id ?? 'new'} doc={existing.data ?? null} />
}

function OpeningEditor({ doc }: { doc: Opening | null }) {
  const nav = useNavigate()
  const [storeId, setStoreId] = useState<number | null>(doc?.store_id ?? null)
  const [day, setDay] = useState(doc?.opening_date ?? today())
  const [remarks, setRemarks] = useState(doc?.remarks ?? '')
  const [lines, setLines] = useState<Line[]>(() =>
    doc?.lines?.length
      ? doc.lines.map((l) => ({ key: ++lineKey, item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null }, qty: { qty: l.qty, uom: l.uom }, rate: l.rate, bin_id: l.bin_id, remarks: l.remarks }))
      : [emptyLine()],
  )
  const bins = useBins(storeId ?? 0)
  const last = useRef<HTMLDivElement>(null)
  const filled = lines.filter((l) => l.item && l.qty.qty && l.rate !== '')
  const total = filled.reduce((sum, l) => sum + Number(l.qty.qty) * Number(l.rate), 0)
  const body = (): OpeningLineInput[] => filled.map((l) => ({ item_id: l.item!.id, qty: l.qty.qty, uom: l.qty.uom || l.item!.base_uom, rate: l.rate, bin_id: l.bin_id, remarks: l.remarks }))
  const save = useAction(
    () => (doc ? updateOpening(doc.id, { opening_date: day, remarks, lines: body() }) : createOpening({ store_id: storeId as number, opening_date: day, remarks, lines: body() })),
    { ...refresh, success: (o) => `${o.number} saved as a draft.`, onSuccess: (o) => nav(`${BASE}/opening/${o.id}`) },
  )
  const set = (key: number, patch: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const addLine = () => {
    setLines((ls) => [...ls, emptyLine()])
    // put the cursor in the new line's item box, so a long opening can be typed without the mouse
    setTimeout(() => last.current?.querySelector<HTMLInputElement>('input')?.focus(), 0)
  }
  return (
    <div className="space-y-4">
      <Card className="grid gap-4 p-4 sm:grid-cols-3">
        <Field label="Store" htmlFor="op-store">
          <StorePicker id="op-store" value={storeId} disabled={!!doc} onChange={(sid) => setStoreId(sid)} />
        </Field>
        <Field label="Stock as on" htmlFor="op-date" hint="Movements in this store can only follow it.">
          <Input id="op-date" type="date" max={today()} value={day} onChange={(e) => setDay(e.target.value)} />
        </Field>
        <Field label="Remarks" htmlFor="op-rem"><Input id="op-rem" value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Physical count on taking over" /></Field>
      </Card>
      <Card className="p-0">
        <div className="hidden grid-cols-[minmax(0,2.2fr)_minmax(0,1.6fr)_8rem_8rem_minmax(0,1fr)_2.5rem] gap-2 border-b border-border px-4 py-2 text-xs font-medium text-muted-foreground lg:grid">
          <span>Item</span><span>Quantity</span><span className="text-right">Rate per unit</span><span>Bin</span><span>Remarks</span><span />
        </div>
        {lines.map((l, i) => (
          <div
            key={l.key}
            ref={i === lines.length - 1 ? last : undefined}
            className="grid gap-2 border-b border-border px-4 py-3 last:border-b-0 lg:grid-cols-[minmax(0,2.2fr)_minmax(0,1.6fr)_8rem_8rem_minmax(0,1fr)_2.5rem] lg:items-start"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && i === lines.length - 1) {
                e.preventDefault()
                addLine()
              }
            }}
          >
            <ItemPicker value={l.item} onChange={(item) => set(l.key, { item, qty: { qty: l.qty.qty, uom: item?.base_uom ?? '' } })} />
            <UomQtyInput itemId={l.item?.id ?? null} value={l.qty} onChange={(qty) => set(l.key, { qty })} />
            <Input aria-label="Rate per unit" inputMode="decimal" className="text-right" placeholder="0.00" value={l.rate} disabled={!l.item} onChange={(e) => /^\d*\.?\d{0,4}$/.test(e.target.value) && set(l.key, { rate: e.target.value })} />
            <Select aria-label="Bin" placeholder="No bin" value={l.bin_id ?? ''} disabled={!storeId || !(bins.data ?? []).length} options={(bins.data ?? []).filter((b) => b.is_active).map((b) => ({ value: b.id, label: b.code }))} onChange={(e) => set(l.key, { bin_id: Number(e.target.value) || null })} />
            <Input aria-label="Remarks" value={l.remarks} onChange={(e) => set(l.key, { remarks: e.target.value })} />
            <Button size="icon-sm" variant="ghost" aria-label="Remove line" disabled={lines.length === 1} onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}><Trash2 /></Button>
          </div>
        ))}
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
          <Button variant="outline" size="sm" onClick={addLine}><Plus /> Add line</Button>
          <span className="text-xs text-muted-foreground">Ctrl+Enter on the last line adds another.</span>
          <span className="text-sm">About <strong>{formatINR(total)}</strong> for {filled.length} item{filled.length === 1 ? '' : 's'}</span>
        </div>
      </Card>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={() => nav(doc ? `${BASE}/opening/${doc.id}` : `${BASE}/opening`)}>Back</Button>
        <Button loading={save.isPending} disabled={!storeId || !filled.length} onClick={() => save.mutate()}>Save draft</Button>
      </div>
    </div>
  )
}

/** One opening: its lines, its trail, and the step it can take next. */
export function OpeningView() {
  const { id } = useParams()
  const { can } = useSession()
  const q = useOpening(Number(id))
  const [busy, setBusy] = useState<DocAction | null>(null)
  const step = useAction((v: { action: DocAction; reason?: string }) => openingAction(Number(id), v.action, v.reason), {
    ...refresh,
    success: (o) => `${o.number} is ${o.status.toLowerCase()}.`,
  })
  const d = q.data
  if (!d) return <p className="text-sm text-muted-foreground">{q.isError ? 'This opening cannot be opened.' : 'Loading...'}</p>
  const act = async (action: DocAction, reason?: string) => {
    setBusy(action)
    try {
      await step.mutateAsync({ action, reason })
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-mono text-lg font-semibold">{d.number}</h2>
            <DocStatusBadge status={d.status} />
            <Badge>{SOURCE[d.source]}</Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {d.store_code} - {d.store_name} · stock as on {formatDate(d.opening_date)} · {money(d.total_value)}
          </p>
          {d.remarks && <p className="mt-1 text-sm">{d.remarks}</p>}
          {d.cancel_reason && <p className="mt-1 text-sm text-danger">Cancelled: {d.cancel_reason}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          {d.status === 'DRAFT' && can(storePerm('masters', 'create')) && <Button variant="outline" size="sm" asChild><Link to={`${BASE}/opening/${d.id}/edit`}>Edit</Link></Button>}
          <Button variant="outline" size="sm" asChild><a href={openingPdf(d.id)} target="_blank" rel="noopener"><FileText /> Print</a></Button>
          <DocActionsBar
            status={d.status}
            busy={busy}
            can={{ submit: can(storePerm('masters', 'create')), approve: can(storePerm('masters', 'approve')), post: can(storePerm('masters', 'post')), cancel: can(storePerm('masters', 'cancel')) }}
            onAction={act}
          />
        </div>
      </div>
      <DataTable
        label="Lines"
        rows={d.lines ?? []}
        rowKey={(l) => l.id ?? l.line_no}
        columns={[
          { id: 'n', header: '#', width: '3rem', cell: (l) => l.line_no },
          { id: 'item', header: 'Item', cell: (l) => <div><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}{l.remarks && <div className="text-xs text-muted-foreground">{l.remarks}</div>}</div> },
          { id: 'bin', header: 'Bin', width: '6rem', hideBelow: 'md', cell: (l) => l.bin_code || '-' },
          { id: 'qty', header: 'Quantity', align: 'right', cell: (l) => `${Number(l.qty)} ${l.uom}` },
          { id: 'rate', header: 'Rate', align: 'right', hideBelow: 'md', cell: (l) => formatINR(Number(l.rate)) },
          { id: 'base', header: 'Posted as', align: 'right', hideBelow: 'lg', cell: (l) => <span className="text-muted-foreground">{l.base_qty} {l.base_uom} @ {l.base_rate}</span> },
          { id: 'value', header: 'Value', align: 'right', cell: (l) => <strong>{money(l.value)}</strong> },
        ]}
      />
      <Trail rows={d.trail ?? []} />
    </div>
  )
}

function Trail({ rows }: { rows: NonNullable<Opening['trail']> }) {
  if (!rows.length) return null
  return (
    <Card className="p-4">
      <h3 className="mb-2 text-sm font-semibold">History</h3>
      <ol className="space-y-1.5 text-sm">
        {rows.map((t, i) => (
          <li key={i} className="flex flex-wrap gap-x-2">
            <span className="text-muted-foreground tabular">{t.at.replace('T', ' ')}</span>
            <span>{t.from ? `${t.from.toLowerCase()} → ${t.to.toLowerCase()}` : `created as ${t.to.toLowerCase()}`}</span>
            <span className="text-muted-foreground">by {t.by || 'the account holder'}</span>
            {t.note && <span className="italic">"{t.note}"</span>}
          </li>
        ))}
      </ol>
    </Card>
  )
}

/** Opening stock from a sheet: choose the file, see every row checked, then make a draft of the good ones. */
export function OpeningImport() {
  const nav = useNavigate()
  const [storeId, setStoreId] = useState<number | null>(null)
  const [day, setDay] = useState(today())
  const [file, setFile] = useState<File | null>(null)
  const [remarks, setRemarks] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [onlyErrors, setOnlyErrors] = useState(false)
  const check = useAction(() => previewSheet(file as File, storeId as number, day), { success: false, onSuccess: (p) => setPreview(p) })
  const make = useAction(() => importSheet(file as File, storeId as number, day, remarks, !!preview?.summary.errors), {
    ...refresh, success: (r) => `${r.opening.number}: ${r.opening.lines_count} items saved as a draft.`, onSuccess: (r) => nav(`${BASE}/opening/${r.opening.id}`),
  })
  const rows = useMemo(() => (preview?.rows ?? []).filter((r) => !onlyErrors || r.errors.length), [preview, onlyErrors])
  const ready = !!storeId && !!file && !!day
  return (
    <div className="space-y-4">
      <Card className="grid gap-4 p-4 sm:grid-cols-[1fr_12rem_1fr_auto] sm:items-end">
        <Field label="Store" htmlFor="imp-store"><StorePicker id="imp-store" value={storeId} onChange={(sid) => { setStoreId(sid); setPreview(null) }} /></Field>
        <Field label="Stock as on" htmlFor="imp-date"><Input id="imp-date" type="date" max={today()} value={day} onChange={(e) => { setDay(e.target.value); setPreview(null) }} /></Field>
        <Field label="Sheet (CSV)" htmlFor="imp-file" hint="Columns: item_code, qty, uom, rate, bin_code, remarks">
          <Input id="imp-file" type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null) }} />
        </Field>
        <div className="flex gap-2">
          <Button variant="outline" asChild><a href={OPENING_TEMPLATE}><FileSpreadsheet /> Template</a></Button>
          <Button disabled={!ready} loading={check.isPending} onClick={() => check.mutate()}>Check sheet</Button>
        </div>
      </Card>
      {preview && (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Badge tone="success">{preview.summary.ok} good</Badge>
            {preview.summary.errors > 0 && <Badge tone="danger">{preview.summary.errors} with problems</Badge>}
            <span>worth {money(preview.summary.total_value)}</span>
            <label className="flex items-center gap-2"><input type="checkbox" checked={onlyErrors} onChange={(e) => setOnlyErrors(e.target.checked)} /> Only rows with problems</label>
          </div>
          <DataTable
            label="Rows of the sheet"
            rows={rows}
            rowKey={(r) => r.line_no}
            rowClassName={(r) => (r.errors.length ? 'bg-danger-soft/40' : undefined)}
            columns={[
              { id: 'n', header: 'Row', width: '4rem', cell: (r) => r.line_no /* counting the rows with something in them */ },
              { id: 'item', header: 'Item', cell: (r) => <div><span className="font-mono text-xs">{r.item_code}</span> {r.item_name}</div> },
              { id: 'qty', header: 'Quantity', align: 'right', cell: (r) => `${r.qty ?? ''} ${r.uom ?? ''}` },
              { id: 'base', header: 'Posted as', align: 'right', hideBelow: 'md', cell: (r) => (r.base_qty ? `${r.base_qty} ${r.base_uom} @ ${r.base_rate}` : '') },
              { id: 'value', header: 'Value', align: 'right', cell: (r) => (r.value ? money(r.value) : '') },
              { id: 'err', header: 'Problems', cell: (r) => (r.errors.length ? <ul className="text-xs text-danger">{r.errors.map((e, i) => <li key={i}>{e}</li>)}</ul> : <Badge tone="success">OK</Badge>) },
            ]}
          />
          <Card className="flex flex-wrap items-end gap-3 p-4">
            <Field label="Remarks" htmlFor="imp-rem" className="min-w-0 flex-1"><Textarea id="imp-rem" rows={1} value={remarks} onChange={(e) => setRemarks(e.target.value)} /></Field>
            <Button disabled={!preview.summary.ok} loading={make.isPending} onClick={() => make.mutate()}>
              {preview.summary.errors ? `Make a draft of the ${preview.summary.ok} good rows` : 'Make a draft'}
            </Button>
          </Card>
        </>
      )}
    </div>
  )
}
