import { useQuery } from '@tanstack/react-query'
import { Select } from '@/components/ui'
import { storeGet } from '@/api/store'
import type { Options } from './types'

export interface CostingValue { project_id: string; work_order_id: string; boq_item_id: string; cost_head: string }
export const emptyCosting: CostingValue = { project_id: '', work_order_id: '', boq_item_id: '', cost_head: '' }
export const useOutwardOptions = () => useQuery({ queryKey: ['store', 'outward', 'options'], staleTime: 60_000, queryFn: () => storeGet<Options>('outward', '/options') })

/** Where the material is charged: project, work order, BOQ item and/or cost head. */
export function Costing({ value, onChange, disabled }: { value: CostingValue; onChange: (v: CostingValue) => void; disabled?: boolean }) {
  const opts = useOutwardOptions()
  const boq = useQuery({ queryKey: ['store', 'outward', 'boq', value.work_order_id], enabled: !!value.work_order_id, queryFn: () => storeGet<{ items: { id: number; item_no: string; description: string }[] }>('outward', `/work-orders/${value.work_order_id}/boq`) })
  const wos = (opts.data?.work_orders ?? []).filter((w) => !value.project_id || String(w.project_id) === value.project_id)
  return (
    <>
      <label className="text-sm">Project<Select disabled={disabled} value={value.project_id} placeholder="Store's project" options={(opts.data?.projects ?? []).map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => onChange({ ...value, project_id: e.target.value, work_order_id: '', boq_item_id: '' })} /></label>
      <label className="text-sm">Work order<Select disabled={disabled} value={value.work_order_id} placeholder="None" options={wos.map((w) => ({ value: w.id, label: w.number }))} onChange={(e) => onChange({ ...value, work_order_id: e.target.value, boq_item_id: '' })} /></label>
      <label className="text-sm">BOQ item<Select disabled={disabled || !value.work_order_id} value={value.boq_item_id} placeholder="None" options={(boq.data?.items ?? []).map((b) => ({ value: b.id, label: `${b.item_no} ${b.description}`.slice(0, 60) }))} onChange={(e) => onChange({ ...value, boq_item_id: e.target.value })} /></label>
      <label className="text-sm">Cost head<Select disabled={disabled} value={value.cost_head} placeholder="None" options={(opts.data?.cost_heads ?? []).map((c) => ({ value: c, label: c.replace(/_/g, ' ').toLowerCase() }))} onChange={(e) => onChange({ ...value, cost_head: e.target.value })} /></label>
    </>
  )
}
export const costingBody = (c: CostingValue) => ({ project_id: c.project_id ? Number(c.project_id) : null, work_order_id: c.work_order_id ? Number(c.work_order_id) : null, boq_item_id: c.boq_item_id ? Number(c.boq_item_id) : null, cost_head: c.cost_head || null })
export const costingFrom = (d: { project_id: number | null; work_order_id: number | null; boq_item_id: number | null; cost_head: string | null }): CostingValue => ({
  project_id: d.project_id ? String(d.project_id) : '', work_order_id: d.work_order_id ? String(d.work_order_id) : '', boq_item_id: d.boq_item_id ? String(d.boq_item_id) : '', cost_head: d.cost_head ?? '',
})
