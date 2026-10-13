import { useState } from 'react'
import { useQuery, type QueryKey } from '@tanstack/react-query'
import { Button, Field, Input, Modal, NumField, Skeleton } from '@/components/ui'
import { get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

interface CreditLine {
  id: number
  description: string
  uom: string
  this_bill_qty: number
  creditable_qty: number
  rate: number
}

interface BillWithLines {
  number: string
  lines?: CreditLine[]
}

export type CreditSide = 'client' | 'contractor'

const base = (side: CreditSide, id: number) => (side === 'client' ? `/api/ra-bills/${id}` : `/api/sub-bills/${id}`)

/**
 * Take back what a certified bill over-billed. The bill itself is never cancelled: its GST and TDS are already in
 * the returns. A credit note reverses the tax in the period it is issued and frees the quantity to be billed again.
 */
export function CreditNoteModal({ side, billId, onClose, invalidate }: { side: CreditSide; billId: number | null; onClose: () => void; invalidate: QueryKey[] }) {
  return (
    <Modal open={billId != null} onOpenChange={(o) => !o && onClose()} title="Issue a credit note" size="lg" description="Take back the quantity that was over-billed. Tax, retention and TDS on it are reversed in today's returns.">
      {billId != null && <Form key={billId} side={side} billId={billId} onClose={onClose} invalidate={invalidate} />}
    </Modal>
  )
}

function Form({ side, billId, onClose, invalidate }: { side: CreditSide; billId: number; onClose: () => void; invalidate: QueryKey[] }) {
  const q = useQuery({
    queryKey: ['credit-note-form', side, billId],
    queryFn: async () => {
      const r = await get<BillWithLines | { bill: BillWithLines }>(base(side, billId))
      return 'bill' in r ? r.bill : r
    },
  })
  const [qty, setQty] = useState<Record<number, number>>({})
  const [reason, setReason] = useState('')
  const [on, setOn] = useState(today())
  const lines = q.data?.lines ?? []
  const picked = lines.filter((l) => (qty[l.id] ?? 0) > 0)
  const over = picked.some((l) => (qty[l.id] ?? 0) > l.creditable_qty + 0.0001)
  const taxable = picked.reduce((s, l) => s + (qty[l.id] ?? 0) * l.rate, 0)
  const save = useAction(
    () => post<{ message: string }>(`${base(side, billId)}/credit-notes`, { lines: picked.map((l) => ({ bill_line_id: l.id, qty: qty[l.id] })), reason, note_date: on }),
    { invalidate: [...invalidate, ['credit-note-form']], onSuccess: onClose },
  )
  if (q.isPending) return <Skeleton className="h-40 w-full" />
  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">
        {q.data?.number}. Enter the quantity to take back against each line. Nothing more than was billed, less earlier credit notes, can be taken back.
      </p>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2">Item</th>
              <th className="px-3 py-2 text-right">Billed</th>
              <th className="px-3 py-2 text-right">Can take back</th>
              <th className="px-3 py-2 text-right">Take back</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.id} className="border-t border-border">
                <td className="px-3 py-2">{l.description} <span className="text-xs text-muted-foreground">({l.uom})</span></td>
                <td className="px-3 py-2 text-right tabular-nums">{l.this_bill_qty}</td>
                <td className="px-3 py-2 text-right tabular-nums">{l.creditable_qty}</td>
                <td className="w-32 px-3 py-2">
                  <NumField aria-label={`Quantity to take back on ${l.description}`} value={qty[l.id] ?? 0} onValue={(v) => setQty((s) => ({ ...s, [l.id]: v }))} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="Why is it being taken back?" htmlFor="cn-reason" className="sm:col-span-2"><Input id="cn-reason" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <Field label="Credit note date" htmlFor="cn-date"><Input id="cn-date" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
      </div>
      <p className="mt-3 text-sm" role="status">
        {over ? <span className="text-danger">One of the lines is more than can be taken back.</span> : <>Taken back before tax: <strong>{formatINR(taxable)}</strong>. Tax, retention and TDS are worked out from the bill's own rates.</>}
      </p>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={over || picked.length === 0 || !reason.trim()} onClick={() => save.mutate()}>Issue the credit note</Button>
      </div>
    </div>
  )
}
