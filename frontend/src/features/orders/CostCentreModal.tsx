import { useState } from 'react'
import { Badge, Button, Field, Input, Modal, NumField } from '@/components/ui'
import { createBudget, orderKeys, updateBudget, useProjectBudgets, type BudgetRow } from '@/api/orders'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'

/**
 * Money set aside on a project for one kind of cost. Every priced line of an
 * order is charged to one, and the order is checked against what is left.
 * The project's cost centres are listed with what is committed against each, and any
 * of them can be raised or brought down - never below what orders have already committed.
 */
export function CostCentreModal({ open, onOpenChange, jobId, orderId }: { open: boolean; onOpenChange: (o: boolean) => void; jobId: number | null; orderId?: number }) {
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [amount, setAmount] = useState(0)
  const [editing, setEditing] = useState<{ id: number; name: string; amount: number } | null>(null)
  const budgets = useProjectBudgets(open ? jobId : null, orderId ?? 0)

  const create = useAction(() => createBudget(jobId!, { name, code, allocated_amount: amount, order_id: orderId }), {
    invalidate: [orderKeys.all],
    onSuccess: () => {
      setName('')
      setCode('')
      setAmount(0)
      onOpenChange(false)
    },
  })
  const change = useAction((b: { row: BudgetRow; amount: number }) => updateBudget(b.row.id, { name: b.row.name, code: b.row.code, allocated_amount: b.amount, order_id: orderId, notes: b.row.notes }), {
    invalidate: [orderKeys.all],
    onSuccess: () => setEditing(null),
  })

  const rows = budgets.data?.budgets ?? []

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title="Set the budget"
      description="The cost centres on this project and how much is set aside for each. One you set or raise is confirmed by whoever approves an order that spends it, unless you can approve orders yourself."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button loading={create.isPending} disabled={!jobId || !name.trim()} onClick={() => create.mutate()}>
            Add cost centre
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {rows.length > 0 && (
          <ul className="divide-y divide-border rounded-lg border border-border text-[13px]" aria-label="Cost centres on this project">
            {rows.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{r.name || r.code}</span>
                  {r.confirmed === false && (
                    <Badge tone="warning" className="ml-1.5">
                      To be confirmed
                    </Badge>
                  )}
                  <span className="block text-xs text-muted-foreground">
                    {formatINR(r.committed + r.this_order)} committed · {formatINR(r.available)} left
                  </span>
                </span>
                {editing?.id === r.id ? (
                  <>
                    <NumField id={`cc-edit-${r.id}`} aria-label={`New allocation for ${r.name}`} className="w-32" value={editing.amount} onValue={(n) => setEditing({ ...editing, amount: n })} />
                    <Button size="sm" loading={change.isPending} onClick={() => change.mutate({ row: r, amount: editing.amount })}>
                      Save
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                      Cancel
                    </Button>
                  </>
                ) : (
                  <>
                    <span className="tabular font-medium">{formatINR(r.allocated)}</span>
                    <Button size="sm" variant="outline" onClick={() => setEditing({ id: r.id, name: r.name, amount: r.allocated })}>
                      Change
                    </Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
        <Field label="New cost centre" htmlFor="cc-name">
          <Input id="cc-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Civil - structure" autoFocus={rows.length === 0} />
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
