import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Field, Input, Select, Textarea } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useAction } from '@/lib/mutate'
import { storePost, storePut } from '@/api/store'
import { inwardKeys, num, today, useDocs, useReturnable, type Doc, type ReturnableLines } from './api'

type Line = ReturnableLines['lines'][number]

/** Goods back to the supplier: choose a posted receipt, then say how much of each line goes back and why. */
export default function ReturnForm({ doc }: { doc?: Doc }) {
  const nav = useNavigate()
  const grns = useDocs('grn', { status: 'POSTED', store_id: 0, q: '' })
  const [grnId, setGrnId] = useState(doc?.grn_id ?? 0)
  const [date, setDate] = useState(doc?.date || today())
  const [reason, setReason] = useState(doc?.reason ?? '')
  const [remarks, setRemarks] = useState(doc?.remarks ?? '')
  const lines = useReturnable(grnId)
  const [qty, setQty] = useState<Record<number, string>>(() => Object.fromEntries((doc?.lines ?? []).map((l) => [l.grn_line_id ?? 0, String(Number(l.qty))])))
  const [why, setWhy] = useState<Record<number, string>>(() => Object.fromEntries((doc?.lines ?? []).map((l) => [l.grn_line_id ?? 0, l.reason ?? ''])))
  const picked = (lines.data?.lines ?? []).filter((l) => Number(qty[l.grn_line_id]) > 0)
  const save = useAction(
    () => {
      const body = { grn_id: grnId, return_date: date, reason, remarks, lines: picked.map((l) => ({ grn_line_id: l.grn_line_id, qty: qty[l.grn_line_id], uom: l.base_uom, reason: why[l.grn_line_id] ?? '' })) }
      return doc ? storePut<Doc>('inward', `/returns/${doc.id}`, body) : storePost<Doc>('inward', '/returns', body)
    },
    { invalidate: [[...inwardKeys.all]], success: (d) => `Saved as draft - ${d.number}`, onSuccess: (d) => nav(`/store/hub/inward/returns/${d.id}`) },
  )
  const columns: TableColumn<Line>[] = [
    { id: 'item', header: 'Item', cell: (l) => <div><div className="font-medium">{l.item_name}</div><div className="font-mono text-xs text-muted-foreground">{l.item_code}</div></div> },
    { id: 'acc', header: 'Accepted', align: 'right', width: '8rem', cell: (l) => `${num(l.accepted)} ${l.base_uom}` },
    { id: 'can', header: 'Can go back', align: 'right', width: '8rem', cell: (l) => `${num(l.returnable)} ${l.base_uom}` },
    { id: 'qty', header: 'Return', width: '9rem', cell: (l) => <Input aria-label={`Quantity of ${l.item_name} to return`} inputMode="decimal" className="text-right" placeholder={`0 ${l.base_uom}`} value={qty[l.grn_line_id] ?? ''} onChange={(e) => setQty((q) => ({ ...q, [l.grn_line_id]: e.target.value }))} /> },
    { id: 'why', header: 'Reason', width: '14rem', cell: (l) => <Input aria-label={`Reason for returning ${l.item_name}`} value={why[l.grn_line_id] ?? ''} onChange={(e) => setWhy((q) => ({ ...q, [l.grn_line_id]: e.target.value }))} /> },
  ]
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (grnId && picked.length) save.mutate() }} className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Receipt to return from" htmlFor="r-grn" hint="Only posted receipts can have goods returned.">
          <Select id="r-grn" value={grnId || ''} placeholder="Choose a receipt" disabled={!!doc} onChange={(e) => { setGrnId(Number(e.target.value) || 0); setQty({}); setWhy({}) }}
            options={(grns.data?.items ?? []).map((g) => ({ value: g.id, label: `${g.number} - ${g.supplier_name || 'no supplier'}` }))} />
        </Field>
        <Field label="Return date" htmlFor="r-date"><Input id="r-date" type="date" max={today()} value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Reason" htmlFor="r-reason"><Input id="r-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Damaged, wrong grade..." /></Field>
        <Field label="Remarks" htmlFor="r-rem" className="sm:col-span-2 lg:col-span-3"><Textarea id="r-rem" rows={1} value={remarks} onChange={(e) => setRemarks(e.target.value)} /></Field>
      </div>
      {grnId > 0 && <DataTable label="Receipt lines" rows={lines.data?.lines ?? []} loading={lines.isPending} columns={columns} rowKey={(l) => l.grn_line_id} />}
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button type="button" variant="ghost" onClick={() => nav(doc ? `/store/hub/inward/returns/${doc.id}` : '/store/hub/inward/returns')}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!grnId || !picked.length}>{doc ? 'Save changes' : 'Save as draft'}</Button>
      </div>
    </form>
  )
}
