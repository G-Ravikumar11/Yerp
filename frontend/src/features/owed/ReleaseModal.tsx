import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { owedKeys, raiseRelease, type Position } from '@/api/owed'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { useSession } from '@/lib/session'

/** Give retention back (to a contractor) or claim it back (from the client), in whole or in stages. */
export function ReleaseModal({ position, stages, onClose }: { position: Position | null; stages: string[]; onClose: () => void }) {
  const client = position?.side === 'client'
  return (
    <Modal open={!!position} onOpenChange={(o) => !o && onClose()} title={position ? (client ? `Claim retention back from ${position.party || 'the client'}` : `Release retention to ${position.party || 'the contractor'}`) : 'Release'}>
      {position && <Form key={`${position.side}-${position.order_id}`} p={position} stages={stages} onClose={onClose} />}
    </Modal>
  )
}

function Form({ p, stages, onClose }: { p: Position; stages: string[]; onClose: () => void }) {
  const [stage, setStage] = useState(p.suggest?.stage ?? 'Part release')
  const [amount, setAmount] = useState(p.suggest?.amount ?? p.balance)
  const [on, setOn] = useState(today())
  const [notes, setNotes] = useState('')
  const [override, setOverride] = useState(false)
  // The client's work order has no defects period of its own: its end is stated here, and carried to later releases.
  const [dlp, setDlp] = useState(p.dlp_ends ?? '')
  const { isOwner } = useSession()
  const client = p.side === 'client'
  const last = stage === 'End of defects period' || (stage !== 'Against a bank guarantee' && amount >= p.balance - 0.009)
  const early = client && last && (!dlp || dlp > on)
  const over = amount > p.balance + 0.009
  // Held for the stage suggested; the server checks again for the stage actually chosen.
  const holds = p.side === 'contractor' ? (p.holds ?? []) : []
  const save = useAction(() => raiseRelease({ side: p.side, order_id: p.order_id, stage, amount, release_on: on, notes, override, dlp_ends: client ? dlp : undefined }), { invalidate: [owedKeys.all], onSuccess: onClose })
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
        <Field label="Release on" htmlFor="rr-date"><Input id="rr-date" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        {client && <Field label="Defects period ends" htmlFor="rr-dlp" hint="The last of the retention is claimed after it"><Input id="rr-dlp" type="date" value={dlp} onChange={(e) => setDlp(e.target.value)} /></Field>}
        <Field label={override ? 'Why release it regardless?' : 'Notes'} htmlFor="rr-notes" className="sm:col-span-2"><Input id="rr-notes" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
      {holds.length > 0 && (
        <div role="alert" className="mt-4 space-y-1 rounded-lg bg-warning-soft p-3 text-[13px] text-warning">
          {holds.map((h) => (
            <p key={h}>{h}</p>
          ))}
          <label className="mt-2 flex items-start gap-2.5">
            <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} className="mt-0.5 size-4 accent-[var(--warning)]" />
            <span>Release it anyway. The reason is kept on the release.</span>
          </label>
        </div>
      )}
      {early && (
        <div role="alert" className="mt-4 space-y-1 rounded-lg bg-warning-soft p-3 text-[13px] text-warning">
          <p>{dlp ? `The defects period runs to ${dlp}.` : 'Give the date the defects period ends.'} The last of the retention is claimed once it is over.</p>
          {isOwner && (
            <label className="mt-2 flex items-start gap-2.5">
              <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} className="mt-0.5 size-4 accent-[var(--warning)]" />
              <span>Release it anyway (the Master only). The reason is kept on the release.</span>
            </label>
          )}
        </div>
      )}
      {p.side === 'contractor' && <p className="mt-3 text-xs text-muted-foreground">Raised by staff, it waits for somebody else to certify it before it is owed.</p>}
      <p className="mt-3 text-sm" role="status">
        {over ? <span className="text-danger">More than the {formatINR(p.balance)} still held.</span> : <><strong>{formatINR(amount)}</strong> {p.side === 'client' ? 'to claim' : 'to pay'}. No GST: the bills already carried it.</>}
      </p>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={over || amount <= 0 || (override && !notes.trim()) || (early && !override)} onClick={() => save.mutate()}>{p.side === 'client' ? 'Raise the claim' : 'Release it'}</Button>
      </div>
    </div>
  )
}
