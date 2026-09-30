import { useState } from 'react'
import { Button, Field, Input, Modal, NumField } from '@/components/ui'
import { createBudget, orderKeys } from '@/api/orders'
import { useAction } from '@/lib/mutate'

/**
 * Money set aside on a project for one kind of cost. Every priced line of an
 * order is charged to one, and the order is checked against what is left.
 */
export function CostCentreModal({ open, onOpenChange, jobId }: { open: boolean; onOpenChange: (o: boolean) => void; jobId: number | null }) {
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [amount, setAmount] = useState(0)

  const create = useAction(() => createBudget(jobId!, { name, code, allocated_amount: amount }), {
    invalidate: [orderKeys.all],
    onSuccess: () => {
      setName('')
      setCode('')
      setAmount(0)
      onOpenChange(false)
    },
  })

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title="Set the budget"
      description="A cost centre on this project and how much is set aside for it."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={create.isPending} disabled={!jobId || !name.trim()} onClick={() => create.mutate()}>
            Add cost centre
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <Field label="Name" htmlFor="cc-name">
          <Input id="cc-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Civil - structure" autoFocus />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Code" htmlFor="cc-code">
            <Input id="cc-code" value={code} onChange={(e) => setCode(e.target.value)} className="font-mono uppercase" placeholder="CIV-1" />
          </Field>
          <Field label="Allocated (₹)" htmlFor="cc-amount">
            <NumField id="cc-amount" value={amount} onValue={setAmount} />
          </Field>
        </div>
      </div>
    </Modal>
  )
}
