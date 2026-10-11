import { useState } from 'react'
import { Badge, Button, ConfirmDialog, Input, Modal, NumField, Skeleton } from '@/components/ui'
import { PromptModal } from '@/components/data/PromptModal'
import { billReceipt, cancelReceipt, discardReceipt, grnKeys, postReceipt, saveReceipt, useReceipt, type Grn } from '@/api/grn'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const tone = (s: string) => (s === 'POSTED' ? 'success' : s === 'CANCELLED' ? 'danger' : 'neutral') as 'success' | 'danger' | 'neutral'

/** One delivery: what arrived against what was ordered, line by line; accepted is derived so the storekeeper sees what will be billed. */
export function ReceiptModal({ id, onClose }: { id: number | null; onClose: () => void }) {
  const q = useReceipt(id)
  const g = q.data
  return (
    <Modal open={id !== null} onOpenChange={(o) => !o && onClose()} title={g ? `${g.number} - ${g.supplier_name} against ${g.purchase_order}` : 'Goods receipt'} size="xl">
      {!g ? <Skeleton className="h-48 w-full" /> : <Body key={`${g.id}-${g.status}`} g={g} onClose={onClose} />}
    </Modal>
  )
}

function Body({ g, onClose }: { g: Grn; onClose: () => void }) {
  const [rows, setRows] = useState(() => g.lines.map((l) => ({ id: l.id, rec: l.received_qty, rej: l.rejected_qty, why: l.rejection_reason })))
  const [cancelling, setCancelling] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const set = (i: number, patch: Partial<(typeof rows)[number]>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  const payload = () => rows.map((r) => ({ id: r.id, received_qty: r.rec, rejected_qty: r.rej, rejection_reason: r.why }))
  const refresh = { invalidate: [grnKeys.all, ['stock']] }
  const save = useAction(async (andPost: boolean) => { const s = await saveReceipt(g.id, payload()); return andPost ? (await postReceipt(s.id)) : { message: 'Saved.' } }, { ...refresh, success: (r) => r.message, onSuccess: (_, andPost) => { if (andPost) onClose() } })
  const bill = useAction(() => billReceipt(g.id), { ...refresh, success: (r) => r.message })
  const cancel = useAction((why: string) => cancelReceipt(g.id, why), { ...refresh, success: (r) => r.message, onSuccess: () => { setCancelling(false); onClose() } })
  const discard = useAction(() => discardReceipt(g.id), { ...refresh, success: (r) => r.message, onSuccess: () => { setDiscarding(false); onClose() } })
  const th = 'px-3 py-2 text-left text-xs font-medium text-muted-foreground'
  return (
    <div>
      <p className="mb-3 flex flex-wrap items-center gap-2 text-sm"><Badge tone={tone(g.status)} dot>{g.status === 'POSTED' ? 'Posted' : g.status === 'CANCELLED' ? 'Cancelled' : 'Draft'}</Badge><span className="text-muted-foreground">{formatDate(g.received_on)}{g.challan_number && ` - challan ${g.challan_number}`}{g.vehicle_number && ` - ${g.vehicle_number}`}{g.received_by_name && ` - received by ${g.received_by_name}`}</span></p>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table aria-label="Lines" className="w-full text-[13px]">
          <thead className="bg-surface"><tr><th className={th}>Item</th><th className={`${th} text-right`}>Ordered</th><th className={`${th} text-right`}>Still to come</th><th className={`${th} w-28 text-right`}>Received</th><th className={`${th} w-28 text-right`}>Rejected</th><th className={`${th} text-right`}>Accepted</th><th className={th}>Why rejected</th><th className={`${th} text-right`}>Value</th></tr></thead>
          <tbody>
            {g.lines.map((l, i) => {
              const r = rows[i]
              const acc = r.rec - r.rej
              const rate = l.rate || l.price || (l.accepted_qty ? l.amount / l.accepted_qty : 0)
              return (
                <tr key={l.id} className="border-t border-border">
                  <td className="px-3 py-2"><span className="font-mono">{l.item_code || '-'}</span><div className="text-xs text-muted-foreground">{l.description}</div></td>
                  <td className="px-3 py-2 text-right tabular">{l.ordered_qty} {l.uom}{l.previously_received > 0 && <div className="text-[11px] text-muted-foreground">{l.previously_received} already in</div>}</td>
                  <td className="px-3 py-2 text-right tabular">{l.ordered_qty - l.previously_received}</td>
                  <td className="px-3 py-2 text-right">{g.editable ? <NumField aria-label={`Received ${l.item_code || l.description}`} value={r.rec} onValue={(n) => set(i, { rec: n })} /> : <span className="tabular">{l.received_qty}</span>}</td>
                  <td className="px-3 py-2 text-right">{g.editable ? <NumField aria-label={`Rejected ${l.item_code || l.description}`} value={r.rej} onValue={(n) => set(i, { rej: n })} /> : <span className="tabular">{l.rejected_qty}</span>}</td>
                  <td className={`px-3 py-2 text-right font-semibold tabular ${acc < 0 ? 'text-danger' : ''}`}>{g.editable ? acc : l.accepted_qty}</td>
                  <td className="px-3 py-2">{g.editable ? <Input aria-label="Why rejected" value={r.why} placeholder="If rejected, why" onChange={(e) => set(i, { why: e.target.value })} /> : l.rejection_reason}</td>
                  <td className="px-3 py-2 text-right tabular">{formatINR(g.editable ? Math.max(0, acc) * rate : l.amount)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">Arrived {formatINR(g.received_value)} - accepted <strong className="text-foreground">{formatINR(g.accepted_value)}</strong>{g.rejected_value > 0 && ` - rejected ${formatINR(g.rejected_value)}`}</p>
      <div className="mt-4 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {(save.error || bill.error) && <p role="alert" className="mr-auto text-[13px] text-danger">{(save.error ?? bill.error)?.message}</p>}
        {g.editable ? (
          <>
            <Button variant="ghost" className="mr-auto text-danger" onClick={() => setDiscarding(true)}>Discard</Button>
            <Button variant="outline" loading={save.isPending} onClick={() => save.mutate(false)}>Save</Button>
            <Button loading={save.isPending} onClick={() => save.mutate(true)}>Save and post</Button>
          </>
        ) : (
          <>
            {g.actions.includes('CANCEL') && <Button variant="ghost" className="mr-auto text-danger" onClick={() => setCancelling(true)}>Cancel this receipt</Button>}
            {g.status === 'POSTED' && <Button loading={bill.isPending} onClick={() => bill.mutate()}>Raise the supplier bill</Button>}
          </>
        )}
      </div>
      <PromptModal open={cancelling} title={`Cancel ${g.number}?`} description="Material posted from it leaves the store again." fields={[{ key: 'why', label: 'Why is this receipt being cancelled?', required: true }]} confirm="Cancel the receipt" busy={cancel.isPending} error={cancel.error?.message} onSubmit={(v) => cancel.mutate(v.why)} onClose={() => setCancelling(false)} />
      <ConfirmDialog open={discarding} onOpenChange={setDiscarding} title={`Discard ${g.number}?`} description="The draft receipt is removed." confirmLabel="Discard it" tone="danger" loading={discard.isPending} onConfirm={() => discard.mutate()} />
    </div>
  )
}
