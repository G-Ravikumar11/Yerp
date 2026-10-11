import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { DataGrid, type Column } from '@/components/grid'
import { Button, Modal } from '@/components/ui'
import { useItems } from '@/api/items'
import { clientOrderKeys, saveBudget, useClientOrder, type ClientOrder } from '@/api/clientOrders'
import { useAction } from '@/lib/mutate'
import { cn, formatINR } from '@/lib/utils'

interface Row {
  fg_code: string
  rm_code: string
  qty: number | null
  rate: number | null
}

const blank = (): Row => ({ fg_code: '', rm_code: '', qty: null, rate: null })
const amount = (r: Row) => (r.qty && r.rate ? Math.round(r.qty * r.rate * 100) / 100 : null)

/** The budget: which raw materials the work sold will consume. It is what turns an order's value into a margin. */
export function BudgetModal({ order, onClose }: { order: ClientOrder | null; onClose: () => void }) {
  return (
    <Modal open={!!order} onOpenChange={(o) => !o && onClose()} size="xl" title={order ? `Budget - ${order.number}` : 'Budget'} description="Say what the work should cost. The margin is the figure an approver is asked to sign off.">
      {order && <BudgetForm key={order.id} id={order.id} onClose={onClose} />}
    </Modal>
  )
}

function BudgetForm({ id, onClose }: { id: number; onClose: () => void }) {
  const order = useClientOrder(id)
  const rm = useItems('RM', '')
  if (order.isPending || rm.isPending) return <p className="py-10 text-center text-sm text-muted-foreground">Opening the order...</p>
  const materials = rm.data?.items ?? []
  if (!order.data || materials.length === 0)
    return (
      <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">
        There are no raw material codes to budget with.{' '}
        <Link to="/store/items" className="text-primary underline underline-offset-2">
          Add some in the Item Master
        </Link>{' '}
        first.
      </p>
    )
  return <Sheet orderId={id} sold={order.data.lines ?? []} value={order.data.total_value} seed={order.data.bom ?? []} materials={materials} onClose={onClose} />
}

function Sheet({ orderId, sold, value, seed, materials, onClose }: { orderId: number; sold: { fg_code: string; item_name: string }[]; value: number; seed: { fg_code: string; rm_code: string; qty: number; rate: number }[]; materials: { item_code: string; item_name: string; last_rate: number }[]; onClose: () => void }) {
  const [rows, setRows] = useState<Row[]>(seed.map((b) => ({ fg_code: b.fg_code, rm_code: b.rm_code, qty: b.qty, rate: b.rate })))
  const rmByCode = useMemo(() => new Map(materials.map((m) => [m.item_code, m])), [materials])
  const columns = useMemo<Column<Row>[]>(
    () => [
      { id: 'fg_code', header: 'Item sold', type: 'select', width: 250, pin: true, options: sold.map((l) => ({ value: l.fg_code, label: `${l.fg_code} - ${l.item_name}` })) },
      {
        id: 'rm_code',
        header: 'Raw material',
        type: 'select',
        width: 260,
        options: materials.map((m) => ({ value: m.item_code, label: `${m.item_code} - ${m.item_name}` })),
        // Choosing a material brings the rate it was last bought at, unless one is already typed.
        set: (r, v) => ({ ...r, rm_code: String(v ?? ''), rate: r.rate || rmByCode.get(String(v))?.last_rate || null }),
      },
      { id: 'qty', header: 'Quantity', type: 'number', width: 110 },
      { id: 'rate', header: 'Rate', type: 'number', decimals: 2, width: 120 },
      { id: 'amount', header: 'Cost', type: 'number', decimals: 2, width: 140, readOnly: true, get: (r) => amount(r), summary: 'sum' },
    ],
    [sold, materials, rmByCode],
  )

  const lines = rows.filter((r) => r.fg_code || r.rm_code || r.qty)
  const cost = lines.reduce((t, r) => t + (amount(r) ?? 0), 0)
  const margin = value - cost
  const pct = value ? Math.round((margin / value) * 1000) / 10 : 0
  const complete = lines.length > 0 && lines.every((r) => r.fg_code && r.rm_code && (r.qty ?? 0) > 0)

  const save = useAction(() => saveBudget(orderId, lines.map((r) => ({ fg_code: r.fg_code, rm_code: r.rm_code, qty: r.qty ?? 0, rate: r.rate ?? 0 }))), {
    invalidate: [clientOrderKeys.all],
    onSuccess: onClose,
  })

  return (
    <div>
      <DataGrid aria-label="Budget lines" columns={columns} rows={rows} onRowsChange={setRows} newRow={blank} minRows={6} maxHeight={320} />
      <div className="mt-5 flex flex-wrap items-end justify-between gap-4 border-t border-border pt-4">
        <dl className="grid grid-cols-3 gap-6 text-sm">
          <div>
            <dt className="text-[13px] text-muted-foreground">Order value</dt>
            <dd className="tabular font-display text-xl font-semibold">{formatINR(value)}</dd>
          </div>
          <div>
            <dt className="text-[13px] text-muted-foreground">Budgeted cost</dt>
            <dd className="tabular font-display text-xl font-semibold">{formatINR(cost)}</dd>
          </div>
          <div>
            <dt className="text-[13px] text-muted-foreground">Margin</dt>
            <dd className={cn('tabular font-display text-xl font-semibold', margin < 0 ? 'text-danger' : 'text-success')}>
              {formatINR(margin)} <span className="text-xs font-normal">{pct}%</span>
            </dd>
          </div>
        </dl>
        <div className="flex items-center gap-2">
          {save.error && (
            <p role="alert" className="max-w-sm text-right text-[13px] text-danger">
              {save.error.message}
            </p>
          )}
          <Button variant="ghost" onClick={onClose}>
            Not now
          </Button>
          <Button loading={save.isPending} disabled={!complete} onClick={() => save.mutate()}>
            Save the budget
          </Button>
        </div>
      </div>
    </div>
  )
}
