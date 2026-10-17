import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, Card, Input, Select } from '@/components/ui'
import { toast } from '@/stores/toast'
import { storeGet, storePost, storePut, useStoreMeta, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker, UomQtyInput } from '../shared'
import { errText, num, type Adjustment, type Count, type Scrap, type Transfer, type WriteoffReq } from './types'

interface Row { key: number; item: StoreItemOption | null; qty: string; uom: string; direction: 'IN' | 'OUT'; rate: string; realised: string; writeoff?: number }
let k = 1
const blank = (): Row => ({ key: k++, item: null, qty: '', uom: '', direction: 'OUT', rate: '', realised: '' })
const asItem = (l: { item_id: number; item_code: string; item_name: string }): StoreItemOption => ({ id: l.item_id, code: l.item_code, name: l.item_name, base_uom: '', uoms: [], category: null })
const ITEMS = '/store/hub/control'

function useSaver<T extends { id: number; number: string }>(kind: string, route: string, build: () => unknown, id?: string) {
  const nav = useNavigate()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => (id ? storePut<T>('control', `/${kind}/${id}`, build()) : storePost<T>('control', `/${kind}`, build())),
    onSuccess: (d) => { toast.success(`${d.number} saved`); qc.invalidateQueries({ queryKey: ['store', 'control'] }); nav(`${ITEMS}/${route}/${d.id}`) },
    onError: (e) => toast.error(errText(e)),
  })
}

function Lines({ rows, setRows, mode }: { rows: Row[]; setRows: (f: (r: Row[]) => Row[]) => void; mode: 'plain' | 'adjust' | 'scrap' }) {
  const set = (key: number, patch: Partial<Row>) => setRows((r) => r.map((x) => (x.key === key ? { ...x, ...patch } : x)))
  return (
    <Card className="overflow-x-auto p-5">
      <table className="w-full min-w-[620px] text-sm">
        <thead><tr className="text-left text-xs uppercase text-muted-foreground"><th className="pb-2 pr-3">Item</th>{mode === 'adjust' && <th className="pb-2 pr-3">In / out</th>}<th className="pb-2 pr-3">Quantity</th>{mode === 'adjust' && <th className="pb-2 pr-3">Rate (stock in)</th>}{mode === 'scrap' && <th className="pb-2 pr-3">Realised ₹</th>}<th /></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="align-top">
              <td className="w-72 py-1 pr-3">{r.writeoff ? <span>{r.item?.name}</span> : <ItemPicker value={r.item} onChange={(item) => set(r.key, { item, uom: item?.base_uom ?? '' })} />}</td>
              {mode === 'adjust' && <td className="w-28 py-1 pr-3"><Select value={r.direction} disabled={!!r.writeoff} options={[{ value: 'IN', label: 'In' }, { value: 'OUT', label: 'Out' }]} onChange={(e) => set(r.key, { direction: e.target.value as 'IN' | 'OUT' })} /></td>}
              <td className="py-1 pr-3">{r.writeoff ? num(r.qty) : <UomQtyInput itemId={r.item?.id ?? null} value={{ qty: r.qty, uom: r.uom }} onChange={(v) => set(r.key, v)} disabled={!r.item} />}</td>
              {mode === 'adjust' && <td className="w-32 py-1 pr-3"><Input inputMode="decimal" disabled={r.direction !== 'IN'} placeholder="average" value={r.rate} onChange={(e) => set(r.key, { rate: e.target.value })} /></td>}
              {mode === 'scrap' && <td className="w-32 py-1 pr-3"><Input inputMode="decimal" value={r.realised} onChange={(e) => set(r.key, { realised: e.target.value })} /></td>}
              <td className="py-1">{!r.writeoff && <Button variant="ghost" size="icon-sm" aria-label="Remove line" onClick={() => setRows((x) => x.filter((y) => y.key !== r.key))}><Trash2 /></Button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Button variant="outline" size="sm" className="mt-3" onClick={() => setRows((r) => [...r, blank()])}><Plus /> Add item</Button>
    </Card>
  )
}

const FormButtons = ({ save, disabled, back }: { save: { isPending: boolean; mutate: () => void }; disabled?: boolean; back: () => void }) => (
  <div className="flex gap-2"><Button loading={save.isPending} disabled={disabled} onClick={() => save.mutate()}>Save draft</Button><Button variant="outline" onClick={back}>Back</Button></div>
)

export function TransferForm() {
  const { id } = useParams()
  const nav = useNavigate()
  const [from, setFrom] = useState<number | null>(null)
  const [to, setTo] = useState<number | null>(null)
  const [vehicle, setVehicle] = useState('')
  const [remarks, setRemarks] = useState('')
  const [rows, setRows] = useState<Row[]>([blank()])
  const existing = useQuery({ queryKey: ['store', 'control', 'transfers', id], enabled: !!id, queryFn: () => storeGet<Transfer>('control', `/transfers/${id}`) })
  useEffect(() => {
    const t = existing.data
    if (!t) return
    setFrom(t.store_id); setTo(t.to_store_id); setVehicle(t.vehicle_no); setRemarks(t.remarks)
    setRows((t.lines ?? []).map((l) => ({ ...blank(), item: asItem(l), qty: l.qty })))
  }, [existing.data])
  const save = useSaver<Transfer>('transfers', 'transfers', () => ({ store_id: from, to_store_id: to, vehicle_no: vehicle, remarks, lines: rows.filter((r) => r.item && r.qty.trim()).map((r) => ({ item_id: r.item!.id, qty: r.qty, uom: r.uom || undefined })) }), id)
  return (
    <div className="space-y-6">
      <Card className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-sm">From store<StorePicker value={from} onChange={(s) => setFrom(s)} disabled={!!id} /></label>
        <label className="text-sm">To store<StorePicker value={to} onChange={(s) => setTo(s)} excludeId={from ?? undefined} /></label>
        <label className="text-sm">Vehicle no.<Input value={vehicle} onChange={(e) => setVehicle(e.target.value)} /></label>
        <label className="text-sm">Remarks<Input value={remarks} onChange={(e) => setRemarks(e.target.value)} /></label>
      </Card>
      <Lines rows={rows} setRows={setRows} mode="plain" />
      <p className="text-xs text-muted-foreground">Stock leaves the sending store when the transfer is posted and stays in transit until the receiving store confirms it.</p>
      <FormButtons save={save} disabled={!from || !to} back={() => nav(ITEMS)} />
    </div>
  )
}

export function CountStart() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [store, setStore] = useState<number | null>(null)
  const [remarks, setRemarks] = useState('')
  const [picked, setPicked] = useState<StoreItemOption[]>([])
  const [item, setItem] = useState<StoreItemOption | null>(null)
  const save = useMutation({
    mutationFn: () => storePost<Count>('control', '/counts', { store_id: store, remarks, item_ids: picked.length ? picked.map((i) => i.id) : undefined }),
    onSuccess: (c) => { toast.success(`${c.number} started; ${c.store_code} is frozen`); qc.invalidateQueries({ queryKey: ['store'] }); nav(`${ITEMS}/counts/${c.id}`) },
    onError: (e) => toast.error(errText(e)),
  })
  return (
    <div className="space-y-6">
      <Card className="grid gap-4 p-5 sm:grid-cols-2">
        <label className="text-sm">Store to count<StorePicker value={store} onChange={(s) => setStore(s)} /></label>
        <label className="text-sm">Remarks<Input value={remarks} onChange={(e) => setRemarks(e.target.value)} /></label>
        <div className="sm:col-span-2">
          <p className="mb-1 text-sm">Count only these items <span className="text-muted-foreground">(leave empty to count everything the store holds)</span></p>
          <div className="mb-2 flex flex-wrap gap-2">{picked.map((i) => <Button key={i.id} variant="soft" size="sm" onClick={() => setPicked(picked.filter((p) => p.id !== i.id))}>{i.name} ×</Button>)}</div>
          <div className="max-w-sm"><ItemPicker value={item} onChange={(i) => { if (i && !picked.some((p) => p.id === i.id)) setPicked([...picked, i]); setItem(null) }} /></div>
        </div>
      </Card>
      <p className="text-sm text-warning">Starting a count freezes the store: nothing can be received or issued there until the count is posted or cancelled.</p>
      <FormButtons save={{ isPending: save.isPending, mutate: () => save.mutate() }} disabled={!store} back={() => nav(ITEMS)} />
    </div>
  )
}

export function AdjustmentForm() {
  const { id } = useParams()
  const nav = useNavigate()
  const meta = useStoreMeta()
  const [store, setStore] = useState<number | null>(null)
  const [kind, setKind] = useState<'STOCK' | 'WASTAGE' | 'WRITEOFF'>('STOCK')
  const [reason, setReason] = useState('')
  const [head, setHead] = useState('')
  const [rows, setRows] = useState<Row[]>([blank()])
  const existing = useQuery({ queryKey: ['store', 'control', 'adjustments', id], enabled: !!id, queryFn: () => storeGet<Adjustment>('control', `/adjustments/${id}`) })
  const requests = useQuery({ queryKey: ['store', 'control', 'writeoff-requests', store], enabled: kind === 'WRITEOFF' && !!store, queryFn: () => storeGet<{ rows: WriteoffReq[] }>('control', `/writeoff-requests?store_id=${store}`) })
  useEffect(() => {
    const a = existing.data
    if (!a) return
    setStore(a.store_id); setKind(a.kind); setReason(a.reason); setHead(a.cost_head ?? '')
    setRows((a.lines ?? []).map((l) => ({ ...blank(), item: asItem(l), qty: l.qty, direction: l.direction, rate: l.direction === 'IN' && Number(l.rate) ? l.rate : '', writeoff: l.writeoff_request_id ?? undefined })))
  }, [existing.data])
  const save = useSaver<Adjustment>('adjustments', 'adjustments', () => ({
    store_id: store, kind, reason, cost_head: kind === 'WASTAGE' ? head || null : null,
    lines: kind === 'WRITEOFF' ? rows.filter((r) => r.writeoff).map((r) => ({ writeoff_request_id: r.writeoff })) : rows.filter((r) => r.item && r.qty.trim()).map((r) => ({ item_id: r.item!.id, qty: r.qty, uom: r.uom || undefined, direction: r.direction, rate: r.direction === 'IN' && r.rate ? r.rate : undefined })),
  }), id)
  return (
    <div className="space-y-6">
      <Card className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-sm">Store<StorePicker value={store} onChange={(s) => { setStore(s); if (kind === 'WRITEOFF') setRows([]) }} disabled={!!id} /></label>
        <label className="text-sm">Kind<Select value={kind} disabled={!!id} options={[{ value: 'STOCK', label: 'Stock correction' }, { value: 'WASTAGE', label: 'Wastage (a cost)' }, { value: 'WRITEOFF', label: 'Write off lost material' }]} onChange={(e) => { setKind(e.target.value as typeof kind); setRows(e.target.value === 'WRITEOFF' ? [] : [blank()]) }} /></label>
        <label className="text-sm lg:col-span-2">Reason<Input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        {kind === 'WASTAGE' && <label className="text-sm">Cost head<Select value={head} placeholder="Store's project" options={(meta.data?.cost_heads ?? []).map((c) => ({ value: c, label: c.replace(/_/g, ' ').toLowerCase() }))} onChange={(e) => setHead(e.target.value)} /></label>}
      </Card>
      {kind === 'WRITEOFF' ? (
        <Card className="p-5">
          <h3 className="mb-2 text-sm font-semibold">Open write-off requests</h3>
          {(requests.data?.rows ?? []).length === 0 && <p className="text-sm text-muted-foreground">{store ? 'None open in this store.' : 'Choose a store.'}</p>}
          {(requests.data?.rows ?? []).map((r) => {
            const on = rows.some((x) => x.writeoff === r.request_id)
            return (
              <label key={r.request_id} className="flex items-center gap-3 py-1 text-sm">
                <input type="checkbox" checked={on} onChange={() => setRows(on ? rows.filter((x) => x.writeoff !== r.request_id) : [...rows, { ...blank(), item: asItem(r), qty: r.qty, writeoff: r.request_id }])} />
                {r.item_name} · {num(r.qty)} · {r.reason}
              </label>
            )
          })}
        </Card>
      ) : <Lines rows={rows} setRows={setRows} mode="adjust" />}
      <FormButtons save={save} disabled={!store || !reason.trim()} back={() => nav(ITEMS)} />
    </div>
  )
}

export function ScrapForm() {
  const { id } = useParams()
  const nav = useNavigate()
  const [store, setStore] = useState<number | null>(null)
  const [buyer, setBuyer] = useState('')
  const [reason, setReason] = useState('')
  const [rows, setRows] = useState<Row[]>([blank()])
  const existing = useQuery({ queryKey: ['store', 'control', 'scrap', id], enabled: !!id, queryFn: () => storeGet<Scrap>('control', `/scrap/${id}`) })
  useEffect(() => {
    const s = existing.data
    if (!s) return
    setStore(s.store_id); setBuyer(s.buyer); setReason(s.reason)
    setRows((s.lines ?? []).map((l) => ({ ...blank(), item: asItem(l), qty: l.qty, realised: l.realised_value })))
  }, [existing.data])
  const save = useSaver<Scrap>('scrap', 'scrap', () => ({ store_id: store, buyer, reason, lines: rows.filter((r) => r.item && r.qty.trim()).map((r) => ({ item_id: r.item!.id, qty: r.qty, uom: r.uom || undefined, realised_value: r.realised || '0' })) }), id)
  return (
    <div className="space-y-6">
      <Card className="grid gap-4 p-5 sm:grid-cols-3">
        <label className="text-sm">Store<StorePicker value={store} onChange={(s) => setStore(s)} disabled={!!id} /></label>
        <label className="text-sm">Sold to<Input value={buyer} onChange={(e) => setBuyer(e.target.value)} /></label>
        <label className="text-sm">Why it is scrap<Input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      </Card>
      <Lines rows={rows} setRows={setRows} mode="scrap" />
      <FormButtons save={save} disabled={!store || !reason.trim()} back={() => nav(ITEMS)} />
    </div>
  )
}
