import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Link2, Pencil, Printer, Trash2 } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Select, Skeleton } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storeDelete, storePerm, storePost } from '@/api/store'
import { ATTACH_TYPE, AttachButton, DocActionsBar, DocStatusBadge, type DocAction } from '../shared'
import { dmy, inwardKeys, kindOf, money, num, useDoc, usePoOptions, type Doc, type DocLine, type InwardKind } from './api'

const QC_TONE = { NOT_REQUIRED: 'neutral', PENDING: 'warning', PASSED: 'success', FAILED: 'danger' } as const

/** One inward document: its header, lines and history, the actions its status allows, and its printed form. */
export default function DocPage() {
  const { kind: key, id } = useParams()
  const kind = kindOf(key)
  const nav = useNavigate()
  const qc = useQueryClient()
  const { can } = useSession()
  const q = useDoc((kind?.key ?? 'grn') as InwardKind, Number(id))
  const [checking, setChecking] = useState<DocLine | null>(null)
  const [discarding, setDiscarding] = useState(false)
  const [linking, setLinking] = useState(false)
  const doc = q.data
  const run = useAction(({ action, reason }: { action: DocAction; reason?: string }) => storePost<Doc>('inward', `/${kind?.key}/${id}/${action}`, { reason: reason ?? '' }), {
    invalidate: [[...inwardKeys.all], ['store', 'lookup']],
    success: (d, v) => ({ submit: 'Submitted', approve: 'Approved', post: 'Posted to stock', cancel: 'Cancelled' })[v.action] + (d.number ? ` - ${d.number}` : ''),
  })
  const discard = useAction(() => storeDelete<{ message: string }>('inward', `/${kind?.key}/${id}`), {
    invalidate: [[...inwardKeys.all]],
    onSuccess: () => nav(`/store/hub/inward/${kind?.key}`),
  })
  if (!kind) return <p className="text-sm text-muted-foreground">There is no such document type.</p>
  const back = (
    <Link to={`/store/hub/inward/${kind.key}`} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> {kind.plural}</Link>
  )
  if (q.isPending) return <div>{back}<Skeleton className="h-40 w-full" /></div>
  if (q.isError || !doc) return <div>{back}<p role="alert" className="text-sm text-danger">Could not load this {kind.label.toLowerCase()}.</p></div>

  const isGrn = kind.key === 'grn'
  const canQc = can(storePerm('inward', 'approve')) && isGrn && (doc.status === 'DRAFT' || doc.status === 'SUBMITTED')
  const columns: TableColumn<DocLine>[] = [
    { id: 'item', header: 'Item', cell: (l) => <div><div className="font-medium">{l.item_name}</div><div className="font-mono text-xs text-muted-foreground">{l.item_code}</div></div> },
    ...(isGrn
      ? ([
          { id: 'got', header: 'Received', align: 'right', width: '9rem', cell: (l) => <div>{num(l.entry_qty)} {l.entry_uom}{l.entry_uom !== l.base_uom && <div className="text-xs text-muted-foreground">= {num(l.received_qty)} {l.base_uom}</div>}</div> },
          { id: 'acc', header: 'Accepted', align: 'right', width: '7rem', cell: (l) => `${num(l.accepted_qty)} ${l.base_uom}` },
          { id: 'rej', header: 'Rejected', align: 'right', width: '7rem', hideBelow: 'md', cell: (l) => (Number(l.rejected_qty) ? <span title={l.reject_reason}>{num(l.rejected_qty)}</span> : '-') },
          { id: 'rate', header: 'Rate', align: 'right', width: '7rem', hideBelow: 'md', cell: (l) => `${money(l.rate)}/${l.base_uom}` },
          {
            id: 'qc',
            header: 'Quality check',
            width: '11rem',
            cell: (l) => (l.qc_status === 'NOT_REQUIRED' ? <span className="text-muted-foreground">Not needed</span> : (
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone={QC_TONE[l.qc_status ?? 'PENDING']} dot>{(l.qc_status ?? '').toLowerCase()}</Badge>
                {canQc && <Button size="sm" variant="outline" onClick={() => setChecking(l)}>{l.qc_status === 'PENDING' ? 'Record' : 'Change'}</Button>}
              </div>
            )),
          },
        ] as TableColumn<DocLine>[])
      : kind.key === 'returns'
        ? ([
            { id: 'qty', header: 'Returned', align: 'right', width: '10rem', cell: (l) => `${num(l.qty)} ${l.base_uom}` },
            { id: 'reason', header: 'Reason', cell: (l) => l.reason || '-' },
          ] as TableColumn<DocLine>[])
        : ([
            { id: 'qty', header: 'Quantity', align: 'right', width: '10rem', cell: (l) => <div>{num(l.entry_qty)} {l.entry_uom}{l.entry_uom !== l.base_uom && <div className="text-xs text-muted-foreground">= {num(l.qty)} {l.base_uom}</div>}</div> },
            { id: 'rate', header: 'Rate', align: 'right', width: '8rem', cell: (l) => `${money(l.rate)}/${l.base_uom}` },
            { id: 'val', header: 'Value', align: 'right', width: '8rem', cell: (l) => money(String(Number(l.qty) * Number(l.rate))) },
          ] as TableColumn<DocLine>[])),
  ]
  const facts: [string, string][] = [
    ['Store', `${doc.store_code} - ${doc.store_name}`],
    ['Date', dmy(doc.date)],
    ...(isGrn && doc.gate_delivery ? ([['Gate delivery', doc.driver_remarks || '-']] as [string, string][]) : []),
    ...(isGrn ? ([['Purchase order', doc.po_number || (doc.gate_delivery ? 'Not linked yet' : '-')], ['Supplier', doc.supplier_name || '-'], ['Challan', [doc.challan_no, doc.challan_date && dmy(doc.challan_date)].filter(Boolean).join(' / ') || '-'], ['Vehicle', doc.vehicle_no || '-'], ['Project', doc.project || '-']] as [string, string][]) : []),
    ...(kind.key === 'returns' ? ([['Against receipt', doc.grn_number || '-'], ['Supplier', doc.supplier_name || '-'], ['Reason', doc.reason || '-']] as [string, string][]) : []),
    ...(kind.key === 'client-supply' ? ([['Project', doc.project || '-'], ['Client reference', doc.client_ref || '-']] as [string, string][]) : []),
    ['Remarks', doc.remarks || '-'],
    ['Made by', `${doc.created_by || '-'}${doc.created_at ? ' on ' + dmy(doc.created_at) : ''}`],
  ]
  return (
    <div>
      {back}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-mono text-lg font-semibold">{doc.number}</h2>
          <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground"><DocStatusBadge status={doc.status} /> {kind.label}{doc.value && Number(doc.value) > 0 ? ` worth ${money(doc.value)}` : ''}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isGrn && doc.gate_delivery && !doc.po_id && doc.status === 'POSTED' && can(storePerm('inward', 'create')) && <Button onClick={() => setLinking(true)}><Link2 /> Link to purchase order</Button>}
          <AttachButton type={(ATTACH_TYPE.inward as Record<string, string>)[kind.key]} id={doc.id} title={doc.number} />
          <Button variant="outline" asChild><a href={`/api/store/inward/${kind.key}/${doc.id}/print`} target="_blank" rel="noreferrer"><Printer /> Print</a></Button>
          {doc.status === 'DRAFT' && can(storePerm('inward', 'create')) && (
            <>
              <Button variant="outline" onClick={() => nav(`/store/hub/inward/${kind.key}/${doc.id}/edit`)}><Pencil /> Edit</Button>
              <Button variant="ghost" onClick={() => setDiscarding(true)}><Trash2 /> Delete draft</Button>
            </>
          )}
          <DocActionsBar
            status={doc.status}
            busy={run.isPending ? (run.variables?.action ?? null) : null}
            can={{ submit: can(storePerm('inward', 'create')), approve: can(storePerm('inward', 'approve')), post: can(storePerm('inward', 'post')), cancel: can(storePerm('inward', 'cancel')) }}
            onAction={(action, reason) => run.mutateAsync({ action, reason }).then(() => undefined, () => { throw new Error('rejected') })}
          />
        </div>
      </div>
      {doc.status === 'CANCELLED' && <p role="status" className="mb-4 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">Cancelled{doc.cancel_reason ? `: ${doc.cancel_reason}` : ''}.</p>}
      {isGrn && doc.gate_delivery && !doc.po_id && doc.status !== 'CANCELLED' && <p role="status" className="mb-4 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">Gate delivery with no purchase order yet: its value is the rate taken at the gate until it is linked to the order.</p>}
      {isGrn && doc.gate_delivery && doc.po_id && <p role="status" className="mb-4 rounded-lg bg-surface px-3 py-2 text-sm">Linked to {doc.po_number} by {doc.linked_by || 'the account holder'}{doc.linked_at ? ` on ${dmy(doc.linked_at)}` : ''}. {Number(doc.price_variance) ? `The order's rate comes to ${money(String(Math.abs(Number(doc.price_variance))))} ${Number(doc.price_variance) > 0 ? 'more' : 'less'} than the rate it was received at.` : 'It was received at the order\'s rate.'}</p>}
      {isGrn && (doc.qc_pending ?? 0) > 0 && doc.status !== 'CANCELLED' && <p role="status" className="mb-4 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">{doc.qc_pending} line{doc.qc_pending === 1 ? '' : 's'} still need a quality check before this can be submitted.</p>}
      <dl className="mb-5 grid gap-x-6 gap-y-2 rounded-xl border border-border bg-card p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
        {facts.map(([k, v]) => <div key={k}><dt className="text-xs uppercase tracking-wide text-muted-foreground">{k}</dt><dd className="font-medium">{v}</dd></div>)}
      </dl>
      <DataTable label="Lines" rows={doc.lines ?? []} columns={columns} rowKey={(l) => l.id} />
      <section aria-labelledby="doc-history" className="mt-6">
        <h3 id="doc-history" className="mb-2 border-b pb-1 text-sm font-semibold">History</h3>
        <ul className="space-y-1 text-sm">
          {(doc.history ?? []).map((h, i) => (
            <li key={i}><span className="font-medium capitalize">{h.action}</span>{h.to && h.from !== h.to ? ` (${h.from ? h.from.toLowerCase() + ' to ' : ''}${h.to.toLowerCase()})` : ''} by {h.by || 'the account holder'} on {dmy(h.at)}{h.note ? ` - ${h.note}` : ''}</li>
          ))}
        </ul>
      </section>
      {linking && <LinkPoModal doc={doc} onClose={() => setLinking(false)} />}
      {checking && <QcModal doc={doc} line={checking} onClose={() => { setChecking(null); void qc.invalidateQueries({ queryKey: [...inwardKeys.all] }) }} />}
      <ConfirmDialog open={discarding} onOpenChange={setDiscarding} title="Delete this draft?" description="Nothing has moved in stock. The number it used is not given back." confirmLabel="Delete" tone="danger" onConfirm={() => { discard.mutate(); setDiscarding(false) }} />
    </div>
  )
}

function QcModal({ doc, line, onClose }: { doc: Doc; line: DocLine; onClose: () => void }) {
  const [result, setResult] = useState<'PASSED' | 'FAILED'>(line.qc_status === 'FAILED' ? 'FAILED' : 'PASSED')
  const [rejected, setRejected] = useState(Number(line.rejected_qty) && line.qc_status === 'PASSED' ? String(Number(line.rejected_qty)) : '')
  const [note, setNote] = useState(line.qc_note ?? '')
  const save = useAction(() => storePost<Doc>('inward', `/grn/${doc.id}/qc/${line.id}`, { result, rejected_qty: result === 'PASSED' ? rejected : '', note }), {
    invalidate: [[...inwardKeys.all]],
    success: 'Quality check recorded',
    onSuccess: onClose,
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Quality check - ${line.item_name}`} description={`${num(line.received_qty)} ${line.base_uom} received. Only what passes goes into stock.`}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }} className="grid gap-4">
        <Field label="Result" htmlFor="qc-result">
          <Select id="qc-result" value={result} onChange={(e) => setResult(e.target.value as 'PASSED' | 'FAILED')} options={[{ value: 'PASSED', label: 'Passed' }, { value: 'FAILED', label: 'Failed - reject it all' }]} />
        </Field>
        {result === 'PASSED' && <Field label={`Quantity rejected (${line.base_uom})`} htmlFor="qc-rej" hint="Leave empty if all of it passed."><Input id="qc-rej" inputMode="decimal" value={rejected} onChange={(e) => setRejected(e.target.value)} /></Field>}
        <Field label="Note" htmlFor="qc-note" hint={result === 'FAILED' || rejected ? 'Required: say what was wrong.' : undefined}><Input id="qc-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} /></Field>
        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending}>Record</Button>
        </div>
      </form>
    </Modal>
  )
}

/** Tie a posted gate delivery to the purchase order raised for it: each line to the order's line for its item. */
function LinkPoModal({ doc, onClose }: { doc: Doc; onClose: () => void }) {
  const pos = usePoOptions()
  const [poId, setPoId] = useState(0)
  const [pick, setPick] = useState<Record<number, number>>({})
  const supplier = (doc.supplier_name ?? '').trim().toLowerCase()
  const options = [...(pos.data ?? [])].sort((a, b) => Number(b.supplier_name.trim().toLowerCase() === supplier) - Number(a.supplier_name.trim().toLowerCase() === supplier))
  const po = options.find((p) => p.id === poId)
  const linesFor = (l: DocLine) => (po?.lines ?? []).filter((x) => x.item_id === l.item_id)
  const save = useAction(() => storePost<Doc>('inward', `/grn/${doc.id}/link-po`, { po_id: poId, lines: Object.fromEntries(Object.entries(pick).filter(([, v]) => v)) }), {
    invalidate: [[...inwardKeys.all], ['store', 'lookup']],
    success: (d) => `Linked to ${d.po_number}`,
    onSuccess: onClose,
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={`Link ${doc.number} to its purchase order`}
      description="The order then counts this delivery as received, and its bill can be matched. The stock keeps the value it came in at; any difference from the order's rate is shown on the receipt.">
      <form onSubmit={(e) => { e.preventDefault(); if (poId) save.mutate() }} className="grid gap-4">
        <Field label="Purchase order" htmlFor="lk-po" hint={pos.data && !options.length ? 'No approved order has anything left to receive.' : 'Orders from the same supplier are listed first.'}>
          <Select id="lk-po" value={poId || ''} placeholder="Choose the order" disabled={pos.isPending} onChange={(e) => { setPoId(Number(e.target.value) || 0); setPick({}) }}
            options={options.map((p) => ({ value: p.id, label: `${p.number} - ${p.supplier_name}` }))} />
        </Field>
        {po && (
          <ul className="grid gap-2 text-sm">
            {(doc.lines ?? []).map((l) => {
              const fits = linesFor(l)
              return (
                <li key={l.id} className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] sm:items-center">
                  <div><div className="font-medium">{l.item_name}</div><div className="text-xs text-muted-foreground">{num(l.accepted_qty)} {l.base_uom} accepted at {money(l.rate)}/{l.base_uom}</div></div>
                  {fits.length === 0 ? <p className="text-xs text-danger">The order has no line for this item.</p>
                    : fits.length === 1 ? <p className="text-xs text-muted-foreground">{fits[0].description || fits[0].item_name}: {num(fits[0].pending)} {fits[0].base_uom} still to come at {money(fits[0].price)}/{fits[0].po_uom}</p>
                    : <Select aria-label={`Order line for ${l.item_name}`} value={pick[l.id] || ''} placeholder="Choose the order line" onChange={(e) => setPick((x) => ({ ...x, [l.id]: Number(e.target.value) || 0 }))}
                        options={fits.map((x) => ({ value: x.po_line_id, label: `${x.description || x.item_name} - ${num(x.pending)} ${x.base_uom} to come` }))} />}
                </li>
              )
            })}
          </ul>
        )}
        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!poId}><Link2 /> Link</Button>
        </div>
      </form>
    </Modal>
  )
}

export type { InwardKind }
