import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Card, Input, Select } from '@/components/ui'
import { toast } from '@/stores/toast'
import { storeGet, storePost } from '@/api/store'
import { StorePicker } from '../shared'
import { errText, num, type Grn, type PurchaseReturn } from './types'

interface Returnable { grn: { id: number; number: string; supplier_name: string }; lines: { grn_line_id: number; item_name: string; item_code: string; base_uom: string; returnable_qty: string }[] }

/** A purchase return of goods from a posted GRN (/returns/new, optionally ?grn=ID). */
export function ReturnForm() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [params] = useSearchParams()
  const [storeId, setStoreId] = useState<number | null>(null)
  const [grnId, setGrnId] = useState(params.get('grn') ?? '')
  const [reason, setReason] = useState('')
  const [qty, setQty] = useState<Record<number, string>>({})
  const posted = useQuery({ queryKey: ['store', 'inward', 'grn', 'posted', storeId], enabled: !!storeId, queryFn: () => storeGet<{ rows: Grn[] }>('inward', `/grn?status=POSTED&store_id=${storeId}&limit=100`) })
  const lines = useQuery({ queryKey: ['store', 'inward', 'returnable', grnId], enabled: !!grnId, queryFn: () => storeGet<Returnable>('inward', `/grn/${grnId}/returnable`) })
  const fromGrn = useQuery({ queryKey: ['store', 'inward', 'grn', grnId], enabled: !!grnId && !storeId, queryFn: () => storeGet<Grn>('inward', `/grn/${grnId}`) })
  useEffect(() => { if (fromGrn.data) setStoreId(fromGrn.data.store_id) }, [fromGrn.data])

  const save = useMutation({
    mutationFn: () => storePost<PurchaseReturn>('inward', '/returns', {
      store_id: storeId, grn_id: Number(grnId), reason, supplier_name: lines.data?.grn.supplier_name,
      lines: Object.entries(qty).filter(([, v]) => Number(v) > 0).map(([id, v]) => ({ grn_line_id: Number(id), qty: v })),
    }),
    onSuccess: (r) => { toast.success(`${r.number} saved`); qc.invalidateQueries({ queryKey: ['store', 'inward'] }); nav(`/store/hub/inward/returns/${r.id}`) },
    onError: (e) => toast.error(errText(e)),
  })
  return (
    <div className="space-y-6">
      <Card className="grid gap-4 p-5 sm:grid-cols-2">
        <label className="text-sm">Store<StorePicker value={storeId} onChange={(id) => { setStoreId(id); setGrnId('') }} /></label>
        <label className="text-sm">Goods received on
          <Select value={grnId} placeholder="Choose a posted GRN" options={(posted.data?.rows ?? []).map((g) => ({ value: g.id, label: `${g.number} · ${g.supplier_name}` }))} onChange={(e) => { setGrnId(e.target.value); setQty({}) }} />
        </label>
        <label className="text-sm sm:col-span-2">Reason for return<Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Damaged, wrong grade, excess…" /></label>
      </Card>
      {lines.data && (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Item</th><th className="p-3 text-right">Can still be returned</th><th className="p-3 text-right">Return</th></tr></thead>
            <tbody>
              {lines.data.lines.map((l) => (
                <tr key={l.grn_line_id} className="border-b border-border last:border-0">
                  <td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</td>
                  <td className="p-3 text-right">{num(l.returnable_qty)} {l.base_uom}</td>
                  <td className="p-3 text-right"><Input className="ml-auto w-28 text-right" inputMode="decimal" disabled={Number(l.returnable_qty) <= 0} value={qty[l.grn_line_id] ?? ''} onChange={(e) => setQty({ ...qty, [l.grn_line_id]: e.target.value })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <div className="flex gap-2"><Button loading={save.isPending} disabled={!storeId || !grnId || !reason.trim()} onClick={() => save.mutate()}>Save draft</Button><Button variant="outline" onClick={() => nav('/store/hub/inward')}>Back</Button></div>
    </div>
  )
}
