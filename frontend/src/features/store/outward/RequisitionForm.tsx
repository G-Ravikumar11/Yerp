import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, Card, Input } from '@/components/ui'
import { toast } from '@/stores/toast'
import { storeGet, storePost, storePut, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker, UomQtyInput } from '../shared'
import { Costing, costingBody, costingFrom, emptyCosting } from './Costing'
import { errText, type Requisition } from './types'

interface Row { key: number; item: StoreItemOption | null; qty: string; uom: string }
let k = 1

/** A new material requisition, or the edit of a draft. */
export function RequisitionForm() {
  const { id } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [storeId, setStoreId] = useState<number | null>(null)
  const [costing, setCosting] = useState(emptyCosting)
  const [requiredBy, setRequiredBy] = useState('')
  const [purpose, setPurpose] = useState('')
  const [rows, setRows] = useState<Row[]>([{ key: k++, item: null, qty: '', uom: '' }])
  const existing = useQuery({ queryKey: ['store', 'outward', 'requisitions', id], enabled: !!id, queryFn: () => storeGet<Requisition>('outward', `/requisitions/${id}`) })
  useEffect(() => {
    const r = existing.data
    if (!r) return
    setStoreId(r.store_id); setPurpose(r.purpose); setRequiredBy(r.required_by ?? ''); setCosting(costingFrom(r))
    setRows((r.lines ?? []).map((l) => ({ key: k++, item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null }, qty: l.entered_qty, uom: l.uom })))
  }, [existing.data])
  const set = (key: number, patch: Partial<Row>) => setRows((r) => r.map((x) => (x.key === key ? { ...x, ...patch } : x)))
  const save = useMutation({
    mutationFn: () => {
      const body = { store_id: storeId, ...costingBody(costing), required_by: requiredBy || null, purpose, lines: rows.filter((r) => r.item && r.qty.trim()).map((r) => ({ item_id: r.item!.id, qty: r.qty, uom: r.uom || r.item!.base_uom })) }
      return id ? storePut<Requisition>('outward', `/requisitions/${id}`, body) : storePost<Requisition>('outward', '/requisitions', body)
    },
    onSuccess: (r) => { toast.success(`${r.number} saved`); qc.invalidateQueries({ queryKey: ['store', 'outward'] }); nav(`/store/hub/outward/requisitions/${r.id}`) },
    onError: (e) => toast.error(errText(e)),
  })
  return (
    <div className="space-y-6">
      <Card className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-sm">Store<StorePicker value={storeId} onChange={(sid) => setStoreId(sid)} disabled={!!id} /></label>
        <label className="text-sm">Required by<Input type="date" value={requiredBy} onChange={(e) => setRequiredBy(e.target.value)} /></label>
        <label className="text-sm">Purpose<Input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Slab pour, level 3" /></label>
        <Costing value={costing} onChange={setCosting} />
      </Card>
      <Card className="overflow-x-auto p-5">
        <table className="w-full min-w-[560px] text-sm">
          <thead><tr className="text-left text-xs uppercase text-muted-foreground"><th className="pb-2 pr-3">Item</th><th className="pb-2 pr-3">Quantity</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="align-top">
                <td className="w-80 py-1 pr-3"><ItemPicker value={r.item} onChange={(item) => set(r.key, { item, uom: item?.base_uom ?? '' })} /></td>
                <td className="py-1 pr-3"><UomQtyInput itemId={r.item?.id ?? null} value={{ qty: r.qty, uom: r.uom }} onChange={(v) => set(r.key, v)} disabled={!r.item} /></td>
                <td className="py-1"><Button variant="ghost" size="icon-sm" aria-label="Remove line" onClick={() => setRows((x) => x.filter((y) => y.key !== r.key))}><Trash2 /></Button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <Button variant="outline" size="sm" className="mt-3" onClick={() => setRows((r) => [...r, { key: k++, item: null, qty: '', uom: '' }])}><Plus /> Add item</Button>
      </Card>
      <div className="flex gap-2"><Button loading={save.isPending} disabled={!storeId} onClick={() => save.mutate()}>Save draft</Button><Button variant="outline" onClick={() => nav('/store/hub/outward')}>Back</Button></div>
    </div>
  )
}
