import { useMemo, useState } from 'react'
import { DataGrid, type Column } from '@/components/grid'
import { Button, Modal } from '@/components/ui'
import { estimateKeys, RATE_KINDS, saveAnalysis, type Estimate, type EstimateItem, type RateKind } from '@/api/estimates'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'

interface Row {
  kind: RateKind
  description: string
  uom: string
  quantity_per_unit: number | null
  rate: number | null
  wastage_percent: number | null
}

const blank = (): Row => ({ kind: 'MATERIAL', description: '', uom: '', quantity_per_unit: null, rate: null, wastage_percent: null })
const amount = (r: Row) => (r.quantity_per_unit && r.rate ? r.quantity_per_unit * r.rate * (1 + (r.wastage_percent ?? 0) / 100) : null)

/** The rate build-up: what goes into one unit of the item. The rate is their sum, and it replaces anything typed. */
export function RateAnalysisModal({ estimate, item, onClose }: { estimate: Estimate; item: EstimateItem | null; onClose: () => void }) {
  return (
    <Modal open={!!item} onOpenChange={(o) => !o && onClose()} size="xl" title={item ? `${item.item_no} - ${item.description}` : 'Rate'} description={item ? `Per 1 ${item.uom || 'unit'}. Enter what goes into one unit of this item.` : undefined}>
      {item && <Sheet key={item.id} estimate={estimate} item={item} onClose={onClose} />}
    </Modal>
  )
}

function Sheet({ estimate, item, onClose }: { estimate: Estimate; item: EstimateItem; onClose: () => void }) {
  const [rows, setRows] = useState<Row[]>(() => item.analysis.map((a) => ({ kind: a.kind, description: a.description, uom: a.uom, quantity_per_unit: a.quantity_per_unit, rate: a.rate, wastage_percent: a.wastage_percent || null })))
  const columns = useMemo<Column<Row>[]>(
    () => [
      { id: 'kind', header: 'Kind', type: 'select', width: 130, options: RATE_KINDS, empty: 'MATERIAL', countsAsData: false },
      { id: 'description', header: 'Resource', hint: 'Cement OPC 53', width: 260, pin: true },
      { id: 'uom', header: 'Unit', hint: 'bag', width: 90 },
      { id: 'quantity_per_unit', header: 'Quantity', hint: 'per unit of item', type: 'number', decimals: 3, width: 130 },
      { id: 'rate', header: 'Rate', type: 'number', decimals: 2, width: 120 },
      { id: 'wastage_percent', header: 'Wastage %', type: 'number', width: 110 },
      { id: 'amount', header: 'Amount', type: 'number', decimals: 2, width: 130, readOnly: true, get: (r) => amount(r), summary: 'sum' },
    ],
    [],
  )

  const cost = rows.reduce((t, r) => t + (amount(r) ?? 0), 0)
  const ask = cost * (1 + estimate.overhead_percent / 100) * (1 + estimate.profit_percent / 100)
  const save = useAction(() => saveAnalysis(estimate.id, item.id, rows.filter((r) => r.description.trim() && r.quantity_per_unit).map((r) => ({ kind: r.kind, description: r.description.trim(), uom: r.uom, quantity_per_unit: r.quantity_per_unit ?? 0, rate: r.rate ?? 0, wastage_percent: r.wastage_percent ?? 0 }))), {
    invalidate: [estimateKeys.all],
    success: false,
    onSuccess: onClose,
  })

  return (
    <div>
      <DataGrid aria-label="Rate build-up" columns={columns} rows={rows} onRowsChange={setRows} newRow={blank} minRows={6} maxHeight={300} />
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <p className="text-sm">
          Cost per unit <strong className="tabular">{formatINR(cost)}</strong> · with {estimate.overhead_percent}% overhead and {estimate.profit_percent}% profit, we ask <strong className="tabular">{formatINR(ask)}</strong>
        </p>
        <div className="flex items-center gap-2">
          {save.error && <p role="alert" className="text-[13px] text-danger">{save.error.message}</p>}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>Save the rate</Button>
        </div>
      </div>
    </div>
  )
}
