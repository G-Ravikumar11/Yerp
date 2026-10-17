import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, Card, Input, Select } from '@/components/ui'
import { toast } from '@/stores/toast'
import { storeGet, storePost, storePut, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker, UomQtyInput } from '../shared'
import { errText, type Grn, type PoLine } from './types'

interface Row { key: number; po_line_id: number | null; item: StoreItemOption | null; label: string; qty: string; uom: string; rate: string; batch_no: string; pending?: string; base?: string }
let k = 1
const blank = (): Row => ({ key: k++, po_line_id: null, item: null, label: '', qty: '', uom: '', rate: '', batch_no: '' })

/** A new GRN, or the edit of a draft (/grn/new, /grn/:id/edit). Choose a purchase order to fill the lines from it. */
export function GrnForm() {
  const { id } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [storeId, setStoreId] = useState<number | null>(null)
  const [poId, setPoId] = useState('')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [supplier, setSupplier] = useState('')
  const [challan, setChallan] = useState('')
  const [vehicle, setVehicle] = useState('')
  const [remarks, setRemarks] = useState('')
  const [rows, setRows] = useState<Row[]>([blank()])
  const pos = useQuery({ queryKey: ['store', 'inward', 'pos'], queryFn: () => storeGet<{ pos: { id: number; number: string; supplier_name: string }[] }>('inward', '/pos') })

  const existing = useQuery({ queryKey: ['store', 'inward', 'grn', id], enabled: !!id, queryFn: () => storeGet<Grn>('inward', `/grn/${id}`) })
  useEffect(() => {
    const g = existing.data
    if (!g) return
    setStoreId(g.store_id); setPoId(g.po_id ? String(g.po_id) : ''); setDate(g.grn_date); setSupplier(g.supplier_name); setChallan(g.challan_no); setVehicle(g.vehicle_no); setRemarks(g.remarks)
    setRows((g.lines ?? []).map((l) => ({ key: k++, po_line_id: l.po_line_id, item: { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null }, label: l.item_name, qty: l.entered_qty, uom: l.uom,
      rate: String(Number(l.rate) * Number(l.received_qty) / Number(l.entered_qty || 1)), batch_no: l.batch_no })))
  }, [existing.data])

  const pickPo = async (value: string) => {
    setPoId(value)
    if (!value) return
    const res = await storeGet<{ po: { supplier_name: string }; lines: PoLine[] }>('inward', `/pos/${value}/lines`)
    setSupplier(res.po.supplier_name)
    setRows(res.lines.map((l) => ({ key: k++, po_line_id: l.po_line_id, item: l.item_id ? { id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null } : null,
      label: l.item_name, qty: '', uom: l.po_uom, rate: l.price, batch_no: '', pending: `${l.pending_qty} ${l.base_uom} pending`, base: l.in_item_master ? undefined : 'Not in the item master' })))
  }
  const set = (key: number, patch: Partial<Row>) => setRows((r) => r.map((x) => (x.key === key ? { ...x, ...patch } : x)))

  const save = useMutation({
    mutationFn: () => {
      const lines = rows.filter((r) => r.qty.trim()).map((r) => ({ po_line_id: r.po_line_id, item_id: r.item?.id ?? null, qty: r.qty, uom: r.uom || r.item?.base_uom, rate: r.rate || null, batch_no: r.batch_no }))
      const body = { store_id: storeId, grn_date: date, po_id: poId ? Number(poId) : null, supplier_name: supplier, challan_no: challan, vehicle_no: vehicle, remarks, lines }
      return id ? storePut<Grn>('inward', `/grn/${id}`, body) : storePost<Grn>('inward', '/grn', body)
    },
    onSuccess: (g) => { toast.success(`${g.number} saved`); qc.invalidateQueries({ queryKey: ['store', 'inward'] }); nav(`/store/hub/inward/grn/${g.id}`) },
    onError: (e) => toast.error(errText(e)),
  })

  return (
    <div className="space-y-6">
      <Card className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-sm">Store<StorePicker value={storeId} onChange={(sid) => setStoreId(sid)} disabled={!!id} /></label>
        <label className="text-sm">Date<Input type="date" value={date} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setDate(e.target.value)} /></label>
        <label className="text-sm">Purchase order
          <Select value={poId} disabled={!!id} placeholder="No purchase order" options={(pos.data?.pos ?? []).map((p) => ({ value: p.id, label: `${p.number} · ${p.supplier_name}` }))} onChange={(e) => void pickPo(e.target.value)} />
        </label>
        <label className="text-sm">Supplier<Input value={supplier} onChange={(e) => setSupplier(e.target.value)} /></label>
        <label className="text-sm">Challan no.<Input value={challan} onChange={(e) => setChallan(e.target.value)} /></label>
        <label className="text-sm">Vehicle no.<Input value={vehicle} onChange={(e) => setVehicle(e.target.value)} /></label>
      </Card>
      <Card className="overflow-x-auto p-5">
        <table className="w-full min-w-[720px] text-sm">
          <thead><tr className="text-left text-xs uppercase text-muted-foreground"><th className="pb-2 pr-3">Item</th><th className="pb-2 pr-3">Quantity received</th><th className="pb-2 pr-3">Rate per unit</th><th className="pb-2 pr-3">Batch</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="align-top">
                <td className="w-72 py-1 pr-3">
                  {r.po_line_id ? <div><div>{r.label}</div><div className="text-xs text-muted-foreground">{r.pending}{r.base && <span className="text-danger"> · {r.base}</span>}</div></div>
                    : <ItemPicker value={r.item} onChange={(item) => set(r.key, { item, uom: item?.base_uom ?? '' })} />}
                </td>
                <td className="py-1 pr-3"><UomQtyInput itemId={r.item?.id ?? null} value={{ qty: r.qty, uom: r.uom }} onChange={(v) => set(r.key, v)} disabled={!r.item} /></td>
                <td className="w-32 py-1 pr-3"><Input inputMode="decimal" value={r.rate} onChange={(e) => set(r.key, { rate: e.target.value })} /></td>
                <td className="w-32 py-1 pr-3"><Input value={r.batch_no} onChange={(e) => set(r.key, { batch_no: e.target.value })} /></td>
                <td className="py-1">{!r.po_line_id && <Button variant="ghost" size="icon-sm" aria-label="Remove line" onClick={() => setRows((x) => x.filter((y) => y.key !== r.key))}><Trash2 /></Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Button variant="outline" size="sm" className="mt-3" onClick={() => setRows((r) => [...r, blank()])}><Plus /> Add item</Button>
        <p className="mt-2 text-xs text-muted-foreground">Leave the quantity empty on a purchase-order line that did not arrive.</p>
      </Card>
      <label className="block text-sm">Remarks<Input value={remarks} onChange={(e) => setRemarks(e.target.value)} /></label>
      <div className="flex gap-2"><Button loading={save.isPending} disabled={!storeId} onClick={() => save.mutate()}>Save draft</Button><Button variant="outline" onClick={() => nav('/store/hub/inward')}>Back</Button></div>
    </div>
  )
}
