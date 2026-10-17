import { useState } from 'react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { awardRfq, rfqKeys, type Statement } from '@/api/rfq'
import { allTo, compare, passedOver, plannedOrders } from '@/lib/rfqCompare'
import { useAction } from '@/lib/mutate'
import { cn, formatINR } from '@/lib/utils'

/** What the comparison asked for: everything to one supplier, or each item to its lowest. */
export interface AwardPreset {
  mode: 'lowest_per_line' | 'one_supplier'
  supplier?: string
}

/** The award makes the purchase orders, as drafts. Anybody but the lowest has to be explained, so the file shows why. */
export function AwardModal({ statement, open, preset, onClose }: { statement: Statement; open: boolean; preset: AwardPreset | null; onClose: () => void }) {
  return (
    <Modal open={open && !!preset} onOpenChange={(o) => !o && onClose()} size="lg" title={`Award ${statement.rfq.number}`}
      description="The purchase orders are made as drafts under Purchase Orders, at the rates quoted. Nothing goes to a supplier until you send it.">
      {open && preset && <Form statement={statement} preset={preset} onClose={onClose} />}
    </Modal>
  )
}

function Form({ statement: d, preset, onClose }: { statement: Statement; preset: AwardPreset; onClose: () => void }) {
  const c = compare(d, d.suppliers.map((s) => s.supplier_name))
  const complete = c.suppliers.filter((s) => s.complete)
  const canSplit = !c.split.uncovered.length && d.suppliers.length > 0
  const [mode, setMode] = useState<AwardPreset['mode']>(preset.mode === 'lowest_per_line' && canSplit ? 'lowest_per_line' : 'one_supplier')
  const [supplier, setSupplier] = useState(preset.supplier || c.l1?.supplier_name || complete[0]?.supplier_name || '')
  const [reason, setReason] = useState('')
  const choice = mode === 'one_supplier' ? allTo(d, supplier) : c.split.winners
  const orders = plannedOrders(d, choice)
  const total = orders.reduce((t, o) => t + o.total, 0)
  // Anybody but the lowest, item by item or the whole order over L1, has to say why.
  const overL1 = mode === 'one_supplier' && !!c.l1 && supplier !== c.l1.supplier_name
  const cheaper = mode === 'one_supplier' ? passedOver(d, choice) : []
  const notLowest = overL1 || cheaper.length > 0
  const save = useAction(() => awardRfq(d.rfq.id, { mode, supplier_name: mode === 'one_supplier' ? supplier : '', reason: reason.trim() }), {
    invalidate: [rfqKeys.all, ['purchase-orders']],
    onSuccess: onClose,
  })

  const options: { value: AwardPreset['mode']; title: string; text: string; off?: string }[] = [
    { value: 'one_supplier', title: 'Everything to one supplier', text: 'One purchase order. Simpler to follow up, one delivery to chase.', off: complete.length ? undefined : 'Nobody has quoted every item yet.' },
    { value: 'lowest_per_line', title: 'Each item to its cheapest supplier', text: c.split.vendors > 1 ? `${c.split.vendors} purchase orders${c.splitSaving > 0.5 ? `, ${formatINR(c.splitSaving)} less before GST than giving it all to ${c.l1?.supplier_name}` : ''}.` : 'Every item is cheapest from the same supplier.', off: canSplit ? undefined : 'Some items have no quote at all.' },
  ]

  return (
    <div className="grid gap-5">
      <div role="radiogroup" aria-label="How to award" className="grid gap-2 sm:grid-cols-2">
        {options.map((o) => (
          <button key={o.value} type="button" role="radio" aria-checked={mode === o.value} disabled={!!o.off} onClick={() => setMode(o.value)}
            className={cn('rounded-lg border p-3 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50', mode === o.value ? 'border-primary bg-primary-soft' : 'border-border hover:bg-accent')}>
            <span className="flex items-center gap-2 font-medium">
              <span className={cn('grid size-4 place-items-center rounded-full border', mode === o.value ? 'border-primary' : 'border-input')}>{mode === o.value && <span className="size-2 rounded-full bg-primary" />}</span>
              {o.title}
            </span>
            <span className="mt-1 block pl-6 text-xs text-muted-foreground">{o.off ?? o.text}</span>
          </button>
        ))}
      </div>

      {mode === 'one_supplier' && (
        <Field label="Supplier" htmlFor="aw-sup">
          <Select id="aw-sup" value={supplier} onChange={(e) => setSupplier(e.target.value)}
            options={complete.map((s) => ({ value: s.supplier_name, label: `${c.rank.get(s.supplier_name) ?? ''} ${s.supplier_name} - ${formatINR(s.landed)}`.trim() }))} />
        </Field>
      )}

      <div className="overflow-hidden rounded-lg border border-border">
        <p className="border-b border-border bg-surface px-3 py-2 text-xs font-medium text-muted-foreground">{orders.length === 1 ? 'This makes one purchase order' : `This makes ${orders.length} purchase orders`}</p>
        <ul className="divide-y divide-border text-sm">
          {orders.map((o) => (
            <li key={o.supplier_name} className="flex items-baseline justify-between gap-4 px-3 py-2">
              <span className="min-w-0"><strong className="font-medium">{o.supplier_name}</strong> <span className="text-muted-foreground">· {o.items} {o.items === 1 ? 'item' : 'items'}{o.freight ? ` · transport ${formatINR(o.freight)}` : ''}</span></span>
              <span className="shrink-0 tabular">{formatINR(o.total)}</span>
            </li>
          ))}
        </ul>
        {orders.length > 1 && <p className="flex justify-between border-t border-border px-3 py-2 text-sm font-semibold"><span>Together, with GST and transport</span><span className="tabular">{formatINR(total)}</span></p>}
      </div>

      {notLowest && (
        <div className="grid gap-3 rounded-lg border border-warning/30 bg-warning-soft p-3">
          <div className="grid gap-1 text-[13px]">
            {overL1 && <p><strong>{supplier}</strong> is not the lowest total: {c.l1!.supplier_name} is, at {formatINR(c.l1!.landed)}.</p>}
            {cheaper.length > 0 && (
              <p>Cheaper from someone else: {cheaper.slice(0, 3).map((l) => `${l.description} (${l.lowest})`).join(', ')}{cheaper.length > 3 ? ` and ${cheaper.length - 3} more` : ''}.</p>
            )}
          </div>
          <Field label="Reason for this choice" htmlFor="aw-reason" hint="Needed: it goes on the file with the award, for whoever checks it later.">
            <Input id="aw-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="One delivery for everything; their cement passed the cube test last time" />
          </Field>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!orders.length || (notLowest && !reason.trim())} onClick={() => save.mutate()}>
          {orders.length === 1 ? 'Make the purchase order' : 'Make the purchase orders'}
        </Button>
      </div>
    </div>
  )
}
