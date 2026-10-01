import { useState } from 'react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { awardRfq, rfqKeys, type Statement } from '@/api/rfq'
import { useAction } from '@/lib/mutate'

/** The award makes the purchase orders as drafts. Choosing anybody but the lowest asks why. */
export function AwardModal({ statement, open, onClose }: { statement: Statement | null; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open && !!statement} onOpenChange={(o) => !o && onClose()} title={statement ? `Award ${statement.rfq.number}` : ''} description="The purchase orders are drafts under Purchase Orders.">
      {open && statement && <Form statement={statement} onClose={onClose} />}
    </Modal>
  )
}

function Form({ statement, onClose }: { statement: Statement; onClose: () => void }) {
  const complete = statement.suppliers.filter((s) => s.complete)
  const [mode, setMode] = useState('lowest_per_line')
  const [supplier, setSupplier] = useState(complete.find((s) => s.is_l1)?.supplier_name ?? complete[0]?.supplier_name ?? '')
  const [reason, setReason] = useState('')
  const save = useAction(() => awardRfq(statement.rfq.id, { mode, supplier_name: supplier, reason }), { invalidate: [rfqKeys.all, ['purchase-orders']], success: (r) => `${r.message} They are drafts under Purchase Orders.`, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4">
        <Field label="Award" htmlFor="aw-mode"><Select id="aw-mode" value={mode} onChange={(e) => setMode(e.target.value)} options={[{ value: 'lowest_per_line', label: 'Each line to whoever quoted it lowest' }, { value: 'one_supplier', label: 'Everything to one supplier' }]} /></Field>
        {mode === 'one_supplier' && <Field label="Supplier" htmlFor="aw-sup"><Select id="aw-sup" value={supplier} onChange={(e) => setSupplier(e.target.value)} options={complete.map((s) => ({ value: s.supplier_name, label: `${s.supplier_name}${s.is_l1 ? ' (lowest landed)' : ''}` }))} /></Field>}
        <Field label="Why not the lowest?" htmlFor="aw-reason" hint="Needed if it is anybody but the lowest"><Input id="aw-reason" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => save.mutate()}>Award it</Button>
      </div>
    </div>
  )
}
