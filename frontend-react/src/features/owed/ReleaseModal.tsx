import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { owedKeys, raiseRelease, type Position } from '@/api/owed'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

/** Give retention back (to a gang) or claim it back (from the client), in whole or in stages. */
export function ReleaseModal({ position, stages, onClose }: { position: Position | null; stages: string[]; onClose: () => void }) {
  const client = position?.side === 'client'
  return (
    <Modal open={!!position} onOpenChange={(o) => !o && onClose()} title={position ? (client ? `Claim retention back from ${position.party || 'the client'}` : `Release retention to ${position.party || 'the gang'}`) : 'Release'}>
      {position && <Form key={`${position.side}-${position.order_id}`} p={position} stages={stages} onClose={onClose} />}
    </Modal>
  )
}

function Form({ p, stages, onClose }: { p: Position; stages: string[]; onClose: () => void }) {
  const [stage, setStage] = useState(p.suggest?.stage ?? 'Part release')
  const [amount, setAmount] = useState(p.suggest?.amount ?? p.balance)
  const [gst, setGst] = useState(p.gst_percent)
  const [on, setOn] = useState(today())
  const [notes, setNotes] = useState('')
  const tax = Math.round(amount * gst) / 100
  const over = amount > p.balance + 0.009
  const save = useAction(() => raiseRelease({ side: p.side, order_id: p.order_id, stage, amount, gst_percent: gst, release_on: on, notes }), { invalidate: [owedKeys.all], onSuccess: onClose })
  return (
    <div>
      <p className="mb-4 text-sm text-muted-foreground">
        {p.order_number} · {p.project}
        <br />
        Held on {p.bills} bill{p.bills === 1 ? '' : 's'}: <strong className="text-foreground">{formatINR(p.held)}</strong> · released {formatINR(p.released)} · <strong className="text-foreground">{formatINR(p.balance)} still held</strong>
        {p.dlp_ends && <><br />Defects period {p.dlp_over ? 'ended' : 'ends'} {p.dlp_ends}</>}
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Stage" htmlFor="rr-stage"><Select id="rr-stage" value={stage} onChange={(e) => setStage(e.target.value)} options={stages.map((s) => ({ value: s, label: s }))} /></Field>
        <Field label="Amount" htmlFor="rr-amount"><NumField id="rr-amount" value={amount} onValue={setAmount} /></Field>
        <Field label="GST %" htmlFor="rr-gst"><NumField id="rr-gst" value={gst} onValue={setGst} /></Field>
        <Field label="Release on" htmlFor="rr-date"><Input id="rr-date" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Notes" htmlFor="rr-notes" className="sm:col-span-2"><Input id="rr-notes" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
      <p className="mt-3 text-sm" role="status">
        {over ? <span className="text-danger">More than the {formatINR(p.balance)} still held.</span> : <>GST {formatINR(tax)} · <strong>total {formatINR(amount + tax)}</strong> {p.side === 'client' ? 'to claim' : 'to pay'}</>}
      </p>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={over || amount <= 0} onClick={() => save.mutate()}>{p.side === 'client' ? 'Raise the claim' : 'Release it'}</Button>
      </div>
    </div>
  )
}
