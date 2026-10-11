import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { DataGrid, type Column } from '@/components/grid'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { useItems, type Item } from '@/api/items'
import { buildClientOrder, clientOrderKeys, useJobOptions, type ClientOrder } from '@/api/clientOrders'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'

interface Row {
  code: string
  description: string
  qty: number | null
  rate: number | null
}

const blank = (): Row => ({ code: '', description: '', qty: null, rate: null })
const amount = (r: Row) => (r.qty && r.rate ? Math.round(r.qty * r.rate * 100) / 100 : null)

export function NewClientOrderModal({ open, onOpenChange, staff, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; staff: boolean; onCreated: (o: ClientOrder) => void }) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} size="xl" title="New client work order" description="Pick what is being sold from the item master, then its quantity and the rate the client agreed.">
      {open && <Builder staff={staff} onClose={() => onOpenChange(false)} onCreated={onCreated} />}
    </Modal>
  )
}

function Builder({ staff, onClose, onCreated }: { staff: boolean; onClose: () => void; onCreated: (o: ClientOrder) => void }) {
  const jobs = useJobOptions(staff)
  const master = useItems('FG', '')
  const fg = master.data?.items ?? []
  const [job, setJob] = useState('')
  const [reference, setReference] = useState('')
  const [rows, setRows] = useState<Row[]>([])

  const byCode = useMemo(() => new Map(fg.map((i: Item) => [i.item_code, i])), [fg])
  const columns = useMemo<Column<Row>[]>(
    () => [
      {
        id: 'code',
        header: 'Item',
        hint: 'From the item master',
        type: 'select',
        width: 280,
        pin: true,
        options: fg.map((i) => ({ value: i.item_code, label: `${i.item_code} - ${i.item_name}` })),
        // Choosing an item brings the rate it was last sold at, unless one is already typed.
        set: (r, v) => ({ ...r, code: String(v ?? ''), rate: r.rate || byCode.get(String(v))?.last_rate || null }),
      },
      { id: 'description', header: 'Description', hint: 'Optional', width: 240 },
      { id: 'qty', header: 'Quantity', type: 'number', width: 110 },
      { id: 'rate', header: 'Rate', hint: 'per unit', type: 'number', decimals: 2, width: 120 },
      { id: 'amount', header: 'Amount', type: 'number', decimals: 2, width: 140, readOnly: true, get: (r) => amount(r), summary: 'sum' },
    ],
    [fg, byCode],
  )

  const lines = rows.filter((r) => r.code)
  const total = lines.reduce((t, r) => t + (amount(r) ?? 0), 0)
  const unpriced = lines.filter((r) => !r.rate).length

  const create = useAction(
    () =>
      buildClientOrder({
        job_id: Number(job),
        reference,
        lines: lines.map((r) => ({ code: r.code, qty: r.qty ?? 0, rate: r.rate ?? 0, description: r.description })),
      }),
    { invalidate: [clientOrderKeys.all], onSuccess: (r) => { onClose(); onCreated(r.work_order) } },
  )

  const ready = !!job && lines.length > 0 && total > 0
  return (
    <div>
      <div className="mb-4 grid gap-4 sm:grid-cols-2">
        <Field label="Job" htmlFor="co-job">
          <Select id="co-job" value={job} onChange={(e) => setJob(e.target.value)} placeholder={jobs.isPending ? 'Loading...' : 'Choose the job'} options={(jobs.data ?? []).map((j) => ({ value: j.id, label: `${j.number} - ${j.name}` }))} />
        </Field>
        <Field label="Client's order reference" htmlFor="co-ref" hint="Printed on every bill raised against this order.">
          <Input id="co-ref" maxLength={60} value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Their PO or letter number" />
        </Field>
      </div>

      {!master.isPending && fg.length === 0 ? (
        <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">
          Nothing to sell yet. Name what this order delivers first, with finished-goods codes in the{' '}
          <Link to="/store/items" className="text-primary underline underline-offset-2">
            Item Master
          </Link>
          .
        </p>
      ) : (
        <DataGrid aria-label="Order lines" columns={columns} rows={rows} onRowsChange={setRows} newRow={blank} minRows={6} maxHeight={320} />
      )}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <div>
          <p className="text-[13px] text-muted-foreground">Order value</p>
          <p className="tabular font-display text-2xl font-semibold">{formatINR(total)}</p>
          {unpriced > 0 && <p className="text-xs text-warning">{unpriced === 1 ? '1 line is' : `${unpriced} lines are`} still to price.</p>}
        </div>
        <div className="flex items-center gap-2">
          {create.error && (
            <p role="alert" className="max-w-md text-right text-[13px] text-danger">
              {create.error.message}
            </p>
          )}
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={create.isPending} disabled={!ready} onClick={() => create.mutate()}>
            Create the order
          </Button>
        </div>
      </div>
    </div>
  )
}
