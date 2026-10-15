import { useState } from 'react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { awardRfq, rfqKeys, type Statement } from '@/api/rfq'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'

/** What the comparison asked for: one supplier, each line to its lowest, or each line to its lowest among the vendors compared. */
export interface AwardPreset {
  mode: 'lowest_per_line' | 'one_supplier' | 'per_line'
  supplier?: string
  awards?: { rfq_line_id: number; supplier_name: string }[]
}

/** The award makes the purchase orders as drafts. Choosing anybody but the lowest asks why. */
export function AwardModal({ statement, open, preset, onClose }: { statement: Statement | null; open: boolean; preset?: AwardPreset | null; onClose: () => void }) {
  return (
    <Modal open={open && !!statement} onOpenChange={(o) => !o && onClose()} title={statement ? `Award ${statement.rfq.number}` : ''} description="The purchase orders are drafts under Purchase Orders.">
      {open && statement && <Form statement={statement} preset={preset ?? null} onClose={onClose} />}
    </Modal>
  )
}

function Form({ statement, preset, onClose }: { statement: Statement; preset: AwardPreset | null; onClose: () => void }) {
  const complete = statement.suppliers.filter((s) => s.complete)
  const split = preset?.mode === 'per_line' ? preset.awards ?? [] : []
  const [mode, setMode] = useState<string>(preset?.mode ?? 'lowest_per_line')
  const [supplier, setSupplier] = useState(preset?.supplier ?? complete.find((s) => s.is_l1)?.supplier_name ?? complete[0]?.supplier_name ?? '')
  const [reason, setReason] = useState('')
  // Anybody but the server's own lowest has to be explained, so say so before the buyer presses Award.
  const offer = (lineId: number, name: string) => statement.lines.find((l) => l.rfq_line_id === lineId)?.offers.find((o) => o.supplier_name === name)
  const splitTo = [...new Set(split.map((a) => a.supplier_name))]
  const splitBasic = split.reduce((t, a) => t + (offer(a.rfq_line_id, a.supplier_name)?.amount ?? 0), 0)
  const notLowest = mode === 'one_supplier' ? !!statement.l1 && supplier !== statement.l1 : mode === 'per_line' && split.some((a) => { const l = statement.lines.find((x) => x.rfq_line_id === a.rfq_line_id); return !!l && (offer(a.rfq_line_id, a.supplier_name)?.rate ?? 0) > l.lowest_rate + 0.0001 })
  const save = useAction(() => awardRfq(statement.rfq.id, { mode, supplier_name: supplier, reason, awards: mode === 'per_line' ? split : undefined }), { invalidate: [rfqKeys.all, ['purchase-orders']], success: (r) => `${r.message} They are drafts under Purchase Orders.`, onSuccess: onClose })
  const modes = [{ value: 'lowest_per_line', label: 'Each line to whoever quoted it lowest' }, { value: 'one_supplier', label: 'Everything to one supplier' }]
  if (split.length) modes.splice(1, 0, { value: 'per_line', label: 'Each line to the lowest among the vendors compared' })
  return (
    <div>
      <div className="grid gap-4">
        <Field label="Award" htmlFor="aw-mode"><Select id="aw-mode" value={mode} onChange={(e) => setMode(e.target.value)} options={modes} /></Field>
        {mode === 'per_line' && <p className="text-[13px] text-muted-foreground">{splitTo.length} purchase {splitTo.length === 1 ? 'order' : 'orders'}, {formatINR(splitBasic)} basic: {splitTo.join(', ')}.</p>}
        {mode === 'one_supplier' && <Field label="Supplier" htmlFor="aw-sup"><Select id="aw-sup" value={supplier} onChange={(e) => setSupplier(e.target.value)} options={complete.map((s) => ({ value: s.supplier_name, label: `${s.supplier_name}${s.is_l1 ? ' (lowest landed)' : ''}` }))} /></Field>}
        <Field label="Why not the lowest?" htmlFor="aw-reason" hint={notLowest ? 'Needed: this is not the lowest of every quote received' : 'Needed if it is anybody but the lowest'}><Input id="aw-reason" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={notLowest && !reason.trim()} onClick={() => save.mutate()}>Award it</Button>
      </div>
    </div>
  )
}
