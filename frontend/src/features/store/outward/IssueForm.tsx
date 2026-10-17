import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Button, Card, Input, Select } from '@/components/ui'
import { useSession } from '@/lib/session'
import { toast } from '@/stores/toast'
import { storeGet, storePost, storePut, type StoreItemOption } from '@/api/store'
import { ItemPicker, StorePicker, UomQtyInput } from '../shared'
import { Costing, costingBody, costingFrom, emptyCosting, useOutwardOptions } from './Costing'
import { errText, num, type Issue, type Requisition } from './types'

interface Row { key: number; item: StoreItemOption | null; qty: string; uom: string; chargeable: boolean; recovery: string; hint?: string }
let k = 1
const blank = (): Row => ({ key: k++, item: null, qty: '', uom: '', chargeable: false, recovery: '' })
const asOption = (l: { item_id: number; item_code: string; item_name: string; base_uom: string }): StoreItemOption => ({ id: l.item_id, code: l.item_code, name: l.item_name, base_uom: l.base_uom, uoms: [], category: null })

/** A new issue (/issues/new, optionally ?req=ID to issue against an approved requisition), or the edit of a draft. */
export function IssueForm() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const { can } = useSession()
  const opts = useOutwardOptions()
  const [storeId, setStoreId] = useState<number | null>(null)
  const [reqId, setReqId] = useState<number | null>(params.get('req') ? Number(params.get('req')) : null)
  const [type, setType] = useState<'SITE' | 'SUBCONTRACTOR'>('SITE')
  const [sub, setSub] = useState('')
  const [holderType, setHolderType] = useState('')
  const [holderId, setHolderId] = useState('')
  const [holderName, setHolderName] = useState('')
  const [expected, setExpected] = useState('')
  const [purpose, setPurpose] = useState('')
  const [costing, setCosting] = useState(emptyCosting)
  const [rows, setRows] = useState<Row[]>([blank()])
  const existing = useQuery({ queryKey: ['store', 'outward', 'issues', id], enabled: !!id, queryFn: () => storeGet<Issue>('outward', `/issues/${id}`) })
  const req = useQuery({ queryKey: ['store', 'outward', 'requisitions', String(reqId)], enabled: !!reqId && !id, queryFn: () => storeGet<Requisition>('outward', `/requisitions/${reqId}`) })
  useEffect(() => {
    const r = req.data
    if (!r) return
    setStoreId(r.store_id); setPurpose(r.purpose); setCosting(costingFrom(r))
    const left = (l: { qty: string; issued_qty: string }) => Math.max(Number(l.qty) - Number(l.issued_qty), 0)
    setRows((r.lines ?? []).filter((l) => left(l) > 0).map((l) => ({ ...blank(), item: asOption(l), uom: l.base_uom, qty: String(left(l)), hint: `${num(String(left(l)))} ${l.base_uom} still to issue` })))
  }, [req.data])
  useEffect(() => {
    const d = existing.data
    if (!d) return
    setStoreId(d.store_id); setReqId(d.requisition_id); setType(d.issue_type); setSub(d.subcontractor_id ? String(d.subcontractor_id) : ''); setHolderType(d.issue_type === 'SITE' ? d.holder_type ?? '' : '')
    setHolderId(d.holder_id ? String(d.holder_id) : ''); setHolderName(d.holder_name); setExpected(d.expected_return_date ?? ''); setPurpose(d.purpose); setCosting(costingFrom(d))
    setRows((d.lines ?? []).map((l) => ({ ...blank(), item: asOption(l), qty: l.entered_qty, uom: l.uom, chargeable: l.chargeable, recovery: l.chargeable ? l.recovery_rate : '' })))
  }, [existing.data])
  const set = (key: number, patch: Partial<Row>) => setRows((r) => r.map((x) => (x.key === key ? { ...x, ...patch } : x)))
  const blocked = !reqId && !can('store.outward.direct_issue')
  const save = useMutation({
    mutationFn: () => {
      const body = {
        store_id: storeId, requisition_id: reqId, issue_type: type, subcontractor_id: type === 'SUBCONTRACTOR' && sub ? Number(sub) : null, ...costingBody(costing), purpose,
        holder_type: type === 'SITE' ? holderType || null : null, holder_id: holderId ? Number(holderId) : null, holder_name: holderName, expected_return_date: expected || null,
        lines: rows.filter((r) => r.item && r.qty.trim()).map((r) => ({ item_id: r.item!.id, qty: r.qty, uom: r.uom || r.item!.base_uom, chargeable: r.chargeable, recovery_rate: r.chargeable && r.recovery ? r.recovery : null })),
      }
      return id ? storePut<Issue>('outward', `/issues/${id}`, body) : storePost<Issue>('outward', '/issues', body)
    },
    onSuccess: (d) => { toast.success(`${d.number} saved`); qc.invalidateQueries({ queryKey: ['store', 'outward'] }); nav(`/store/hub/outward/issues/${d.id}`) },
    onError: (e) => toast.error(errText(e)),
  })
  return (
    <div className="space-y-6">
      {reqId
        ? <p className="text-sm text-muted-foreground">Against requisition {req.data?.number ?? existing.data?.requisition_number}. Costing comes from the requisition unless you change it.</p>
        : <p className="text-sm text-muted-foreground">Direct issue, no requisition.{blocked && <span className="text-danger"> You do not have the right to issue material directly.</span>}</p>}
      <Card className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-sm">Store<StorePicker value={storeId} onChange={(sid) => setStoreId(sid)} disabled={!!id || !!reqId} /></label>
        <label className="text-sm">Issued to<Select value={type} options={[{ value: 'SITE', label: 'Site use' }, { value: 'SUBCONTRACTOR', label: 'Subcontractor' }]} onChange={(e) => setType(e.target.value as 'SITE' | 'SUBCONTRACTOR')} /></label>
        {type === 'SUBCONTRACTOR'
          ? <label className="text-sm">Subcontractor<Select value={sub} placeholder="Choose" options={(opts.data?.subcontractors ?? []).map((c) => ({ value: c.id, label: c.name }))} onChange={(e) => setSub(e.target.value)} /></label>
          : <label className="text-sm">Returnables held by<Select value={holderType} placeholder="Not needed" options={[{ value: 'EMPLOYEE', label: 'A staff member' }, { value: 'SUBCONTRACTOR', label: 'A subcontractor' }, { value: 'GANG', label: 'A gang' }]} onChange={(e) => { setHolderType(e.target.value); setHolderId(''); setHolderName('') }} /></label>}
        {type === 'SITE' && holderType === 'EMPLOYEE' && <label className="text-sm">Staff<Select value={holderId} placeholder="Choose" options={(opts.data?.employees ?? []).map((e) => ({ value: e.id, label: e.name }))} onChange={(e) => setHolderId(e.target.value)} /></label>}
        {type === 'SITE' && holderType === 'SUBCONTRACTOR' && <label className="text-sm">Holder<Select value={holderId} placeholder="Choose" options={(opts.data?.subcontractors ?? []).map((c) => ({ value: c.id, label: c.name }))} onChange={(e) => setHolderId(e.target.value)} /></label>}
        {type === 'SITE' && holderType === 'GANG' && <label className="text-sm">Gang name<Input value={holderName} onChange={(e) => setHolderName(e.target.value)} /></label>}
        <label className="text-sm">Expected back by<Input type="date" value={expected} onChange={(e) => setExpected(e.target.value)} /></label>
        <label className="text-sm">Purpose<Input value={purpose} onChange={(e) => setPurpose(e.target.value)} /></label>
        <Costing value={costing} onChange={setCosting} />
      </Card>
      <Card className="overflow-x-auto p-5">
        <table className="w-full min-w-[640px] text-sm">
          <thead><tr className="text-left text-xs uppercase text-muted-foreground"><th className="pb-2 pr-3">Item</th><th className="pb-2 pr-3">Quantity</th>{type === 'SUBCONTRACTOR' && <th className="pb-2 pr-3">Recover from bill</th>}<th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="align-top">
                <td className="w-80 py-1 pr-3">{reqId ? <div>{r.item?.name}<div className="text-xs text-muted-foreground">{r.hint}</div></div> : <ItemPicker value={r.item} onChange={(item) => set(r.key, { item, uom: item?.base_uom ?? '' })} />}</td>
                <td className="py-1 pr-3"><UomQtyInput itemId={r.item?.id ?? null} value={{ qty: r.qty, uom: r.uom }} onChange={(v) => set(r.key, v)} disabled={!r.item} /></td>
                {type === 'SUBCONTRACTOR' && <td className="py-1 pr-3"><label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={r.chargeable} onChange={(e) => set(r.key, { chargeable: e.target.checked })} /> Chargeable</label>{r.chargeable && <Input className="mt-1 w-32" inputMode="decimal" placeholder="Rate / unit" value={r.recovery} onChange={(e) => set(r.key, { recovery: e.target.value })} />}</td>}
                <td className="py-1">{!reqId && <Button variant="ghost" size="icon-sm" aria-label="Remove line" onClick={() => setRows((x) => x.filter((y) => y.key !== r.key))}><Trash2 /></Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!reqId && <Button variant="outline" size="sm" className="mt-3" onClick={() => setRows((r) => [...r, blank()])}><Plus /> Add item</Button>}
        <p className="mt-2 text-xs text-muted-foreground">Stock leaves only when the issue is posted, valued at the store's average rate.</p>
      </Card>
      <div className="flex gap-2"><Button loading={save.isPending} disabled={!storeId || blocked} onClick={() => save.mutate()}>Save draft</Button><Button variant="outline" onClick={() => nav('/store/hub/outward')}>Back</Button></div>
    </div>
  )
}
