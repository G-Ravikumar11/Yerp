import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button, Card, Input, Select, SkeletonRows } from '@/components/ui'
import { useSession } from '@/lib/session'
import { toast } from '@/stores/toast'
import { storeDelete, storeGet, storePerm, storePut, type StoreItemOption } from '@/api/store'
import { ItemPicker } from '../shared'

interface Norm { id: number; boq_item_id: number; boq_label: string; boq_qty: string; boq_uom: string; item_code: string; item_name: string; qty_per_unit: string; wastage_pct: string; theoretical: string }
interface Options { work_orders: { id: number; number: string }[] }
const errText = (e: unknown) => (e as { detail?: string; message?: string })?.detail ?? (e as Error)?.message ?? 'Something went wrong'

/** How much of an item one unit of a BOQ item should take. The consumption report sets issues against this. */
export function Norms() {
  const { can } = useSession()
  const qc = useQueryClient()
  const [wo, setWo] = useState('')
  const [boq, setBoq] = useState('')
  const [item, setItem] = useState<StoreItemOption | null>(null)
  const [per, setPer] = useState('')
  const [waste, setWaste] = useState('0')
  const opts = useQuery({ queryKey: ['store', 'outward', 'options'], staleTime: 60_000, queryFn: () => storeGet<Options>('outward', '/options') })
  const boqItems = useQuery({ queryKey: ['store', 'outward', 'boq', wo], enabled: !!wo, queryFn: () => storeGet<{ items: { id: number; item_no: string; description: string }[] }>('outward', `/work-orders/${wo}/boq`) })
  const list = useQuery({ queryKey: ['store', 'reports', 'norms', wo], enabled: !!wo, queryFn: () => storeGet<{ rows: Norm[] }>('reports', `/norms?work_order_id=${wo}`) })
  const save = useMutation({
    mutationFn: () => storePut('reports', '/norms', { boq_item_id: Number(boq), item_id: item!.id, qty_per_unit: per, wastage_pct: waste || '0' }),
    onSuccess: () => { toast.success('Norm saved'); setItem(null); setPer(''); qc.invalidateQueries({ queryKey: ['store', 'reports'] }) },
    onError: (e) => toast.error(errText(e)),
  })
  const remove = (id: number) => storeDelete('reports', `/norms/${id}`).then(() => { toast.success('Removed'); qc.invalidateQueries({ queryKey: ['store', 'reports'] }) }).catch((e) => toast.error(errText(e)))
  return (
    <div className="space-y-6">
      <Link to="/store/hub/reports" className="text-sm text-primary hover:underline">All reports</Link>
      <Card className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-sm">Work order<Select value={wo} placeholder="Choose" options={(opts.data?.work_orders ?? []).map((w) => ({ value: w.id, label: w.number }))} onChange={(e) => { setWo(e.target.value); setBoq('') }} /></label>
        {can(storePerm('reports', 'create')) && wo && (
          <>
            <label className="text-sm">BOQ item<Select value={boq} placeholder="Choose" options={(boqItems.data?.items ?? []).map((b) => ({ value: b.id, label: `${b.item_no} ${b.description}`.slice(0, 60) }))} onChange={(e) => setBoq(e.target.value)} /></label>
            <label className="text-sm">Item<ItemPicker value={item} onChange={setItem} /></label>
            <label className="text-sm">Per unit of BOQ item<Input inputMode="decimal" value={per} onChange={(e) => setPer(e.target.value)} placeholder={item ? `${item.base_uom} per unit` : ''} /></label>
            <label className="text-sm">Wastage %<Input inputMode="decimal" value={waste} onChange={(e) => setWaste(e.target.value)} /></label>
            <div className="flex items-end"><Button loading={save.isPending} disabled={!boq || !item || !per} onClick={() => save.mutate()}>Save norm</Button></div>
          </>
        )}
      </Card>
      {wo && (list.isLoading ? <SkeletonRows rows={4} cols={4} /> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">BOQ item</th><th className="p-3">Item</th><th className="p-3 text-right">Per unit</th><th className="p-3 text-right">Wastage</th><th className="p-3 text-right">Should take</th><th /></tr></thead>
            <tbody>
              {(list.data?.rows ?? []).map((n) => (
                <tr key={n.id} className="border-b border-border last:border-0">
                  <td className="p-3">{n.boq_label}<div className="text-xs text-muted-foreground">{n.boq_qty} {n.boq_uom}</div></td><td className="p-3">{n.item_name}</td>
                  <td className="p-3 text-right">{Number(n.qty_per_unit)}</td><td className="p-3 text-right">{Number(n.wastage_pct)}%</td><td className="p-3 text-right">{Number(n.theoretical).toLocaleString('en-IN')}</td>
                  <td className="p-3 text-right">{can(storePerm('reports', 'cancel')) && <Button variant="ghost" size="icon-sm" aria-label="Remove norm" onClick={() => void remove(n.id)}><Trash2 /></Button>}</td>
                </tr>
              ))}
              {(list.data?.rows ?? []).length === 0 && <tr><td colSpan={6} className="p-6 text-center text-muted-foreground">No norms set for this work order.</td></tr>}
            </tbody>
          </table>
        </Card>
      ))}
    </div>
  )
}
