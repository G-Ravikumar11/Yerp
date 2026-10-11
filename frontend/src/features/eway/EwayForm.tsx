import { useState } from 'react'
import { Plus, X } from 'lucide-react'
import { Badge, Button, Field, Input, NumField, Select } from '@/components/ui'
import { PromptModal } from '@/components/data/PromptModal'
import { ewKeys, ewayAction, saveEway, type Eway, type EwayLine, type EwayMeta } from '@/api/eway'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'

const blankLine = (): EwayLine => ({ product_name: '', hsn: '', qty: 1, unit: 'Nos', taxable: 0, tax_rate: 0 })
const th = 'px-2 py-2 text-left text-xs font-medium text-muted-foreground'

export function EwayForm({ meta, bill: e, fromTransfer, onClose }: { meta: EwayMeta; bill: Eway | null; fromTransfer: string; onClose: () => void }) {
  const draft = !e || e.status === 'DRAFT'
  const place = (side: 'from' | 'to') => (e ? (meta.places.find((p) => p.name === e[side].name && p.address === e[side].address)?.key ?? '') : side === 'from' ? 'company' : '')
  const [f, setF] = useState({ from_key: place('from'), to_key: place('to'), doc_type: e?.doc_type || 'CHL', doc_no: e?.doc_no || fromTransfer, doc_date: e?.doc_date || today(), sub_type: e?.sub_type || '5', trans_mode: e?.trans_mode || '1', vehicle_no: e?.vehicle_no ?? '', transporter_id: e?.transporter_id ?? '' })
  const [km, setKm] = useState(e?.distance_km ?? 0)
  const [lines, setLines] = useState<EwayLine[]>(e ? e.lines : fromTransfer ? [] : [blankLine()])
  const [recording, setRecording] = useState<'generated' | 'vehicle' | 'cancel' | null>(null)
  const set = (k: keyof typeof f) => (ev: { target: { value: string } }) => setF((x) => ({ ...x, [k]: ev.target.value }))
  const edit = (i: number, patch: Partial<EwayLine>) => setLines((l) => l.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  const lock = !draft
  const save = useAction(() => saveEway(e?.id ?? null, { ...f, distance_km: km, ...(fromTransfer ? { source_type: 'transfer', source_ref: fromTransfer } : {}), ...(lines.length ? { lines } : {}) }), {
    invalidate: [ewKeys.all],
    success: (r) => (r.eway_bill.problems.length ? `Saved - ${r.eway_bill.problems.length} thing(s) still needed.` : 'Saved. Ready for the portal.'),
    onSuccess: () => { if (!e) onClose() },
  })
  const act = useAction((v: { path: 'generated' | 'vehicle' | 'cancel'; body: Record<string, unknown> }) => ewayAction(e?.id as number, v.path, v.body), { invalidate: [ewKeys.all], success: (r) => r.message || 'Done', onSuccess: () => setRecording(null) })
  const places = meta.places.map((p) => ({ value: p.key, label: `${p.name}${p.pincode ? ` (${p.pincode})` : ' (no PIN)'}` }))
  return (
    <div>
      {e && <p className="mb-3 flex flex-wrap items-center gap-2 text-sm"><Badge tone={e.status === 'GENERATED' ? (e.expired ? 'danger' : 'success') : e.status === 'CANCELLED' ? 'neutral' : 'warning'} dot>{e.expired ? 'Expired' : e.status === 'GENERATED' ? 'Issued' : e.status === 'CANCELLED' ? 'Cancelled' : 'Draft'}</Badge>{e.valid_upto && <span className="text-muted-foreground">valid to {e.valid_upto}</span>}</p>}
      <div className="grid gap-4 sm:grid-cols-4">
        <Field label="From" htmlFor="ew-from" className="sm:col-span-2"><Select id="ew-from" value={f.from_key} placeholder="Choose..." disabled={lock} onChange={set('from_key')} options={places} /></Field>
        <Field label="To" htmlFor="ew-to" className="sm:col-span-2"><Select id="ew-to" value={f.to_key} placeholder="Choose..." disabled={lock} onChange={set('to_key')} options={places} /></Field>
        <Field label="Document" htmlFor="ew-dt"><Select id="ew-dt" value={f.doc_type} disabled={lock} onChange={set('doc_type')} options={Object.entries(meta.doc_types).map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label="Document no." htmlFor="ew-dn"><Input id="ew-dn" maxLength={16} value={f.doc_no} disabled={lock} onChange={set('doc_no')} /></Field>
        <Field label="Date" htmlFor="ew-dd"><Input id="ew-dd" type="date" value={f.doc_date} disabled={lock} onChange={set('doc_date')} /></Field>
        <Field label="Why it moves" htmlFor="ew-st"><Select id="ew-st" value={f.sub_type} disabled={lock} onChange={set('sub_type')} options={Object.entries(meta.sub_types).map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label="Distance (km)" htmlFor="ew-km" hint="0 lets the portal work it out"><NumField id="ew-km" value={km} onValue={setKm} disabled={lock} /></Field>
        <Field label="By" htmlFor="ew-mode"><Select id="ew-mode" value={f.trans_mode} disabled={lock} onChange={set('trans_mode')} options={Object.entries(meta.modes).map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label="Vehicle no." htmlFor="ew-veh"><Input id="ew-veh" className="uppercase" value={f.vehicle_no} disabled={lock} placeholder="TS09UB1234" onChange={set('vehicle_no')} /></Field>
        <Field label="Transporter (GSTIN / ID)" htmlFor="ew-tr"><Input id="ew-tr" value={f.transporter_id} disabled={lock} onChange={set('transporter_id')} /></Field>
      </div>
      <div className="mt-4 overflow-x-auto rounded-lg border border-border">
        <table aria-label="Goods" className="w-full text-[13px]">
          <thead className="bg-surface"><tr><th className={th}>Goods</th><th className={th}>HSN</th><th className={th}>Qty</th><th className={th}>Unit</th><th className={th}>Value</th><th className={th}>GST %</th><th /></tr></thead>
          <tbody>
            {lines.length === 0 && <tr><td colSpan={7} className="px-3 py-4 text-muted-foreground">The transfer's lines are filled in when it is saved.</td></tr>}
            {lines.map((l, i) => {
              const ro = lock || !!fromTransfer
              return (
                <tr key={i} className="border-t border-border">
                  <td className="px-2 py-1.5"><Input aria-label={`Goods ${i + 1}`} value={l.product_name} readOnly={ro} onChange={(ev) => edit(i, { product_name: ev.target.value })} /></td>
                  <td className="px-2 py-1.5"><Input aria-label={`HSN ${i + 1}`} value={l.hsn} disabled={lock} onChange={(ev) => edit(i, { hsn: ev.target.value })} /></td>
                  <td className="w-24 px-2 py-1.5"><NumField aria-label={`Qty ${i + 1}`} value={l.qty} readOnly={ro} onValue={(n) => edit(i, { qty: n })} /></td>
                  <td className="w-20 px-2 py-1.5"><Input aria-label={`Unit ${i + 1}`} value={l.unit} readOnly={ro} onChange={(ev) => edit(i, { unit: ev.target.value })} /></td>
                  <td className="w-32 px-2 py-1.5"><NumField aria-label={`Value ${i + 1}`} value={l.taxable} readOnly={ro} onValue={(n) => edit(i, { taxable: n })} /></td>
                  <td className="w-20 px-2 py-1.5"><NumField aria-label={`GST ${i + 1}`} value={l.tax_rate} disabled={lock} onValue={(n) => edit(i, { tax_rate: n })} /></td>
                  <td className="px-2 py-1.5">{draft && !fromTransfer && <button type="button" aria-label={`Remove line ${i + 1}`} onClick={() => setLines(lines.filter((_, j) => j !== i))}><X className="size-4" /></button>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {draft && !fromTransfer && <Button size="sm" variant="ghost" className="mt-1" onClick={() => setLines([...lines, blankLine()])}><Plus /> Line</Button>}
      {e && <p className="mt-3 text-sm">Value {formatINR(e.taxable_value)}{e.igst ? ` - IGST ${formatINR(e.igst)}` : e.cgst ? ` - CGST ${formatINR(e.cgst)} + SGST ${formatINR(e.sgst)}` : ''} - <strong>{formatINR(e.total_value)}</strong>{e.total_value <= meta.threshold && <span className="text-muted-foreground"> (under {formatINR(meta.threshold)}: not required, allowed)</span>}</p>}
      {e && e.problems.length > 0 && <div role="alert" className="mt-3 rounded-lg border border-warning/50 p-3 text-[13px]"><p className="font-semibold">The portal would refuse it for want of:</p><ul className="ml-5 mt-1 list-disc">{e.problems.map((p) => <li key={p}>{p}</li>)}</ul></div>}
      {e && e.vehicle_history.length > 0 && <p className="mt-3 text-xs text-muted-foreground">Vehicle changes:{e.vehicle_history.map((h) => <span key={h} className="block">{h}</span>)}</p>}
      {e?.cancel_reason && <p className="mt-3 text-[13px] text-danger">Cancelled: {e.cancel_reason}</p>}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {(save.error || act.error) && <p role="alert" className="mr-auto text-[13px] text-danger">{(save.error ?? act.error)?.message}</p>}
        {e && e.status !== 'CANCELLED' && <Button variant="ghost" className="text-danger" onClick={() => setRecording('cancel')}>Cancel</Button>}
        {e?.status === 'GENERATED' && <Button variant="outline" onClick={() => setRecording('vehicle')}>Change vehicle</Button>}
        {e && draft && <Button variant="outline" asChild><a href={`/api/eway-bills/${e.id}/json`} onClick={(ev) => { if (e.problems.length) { ev.preventDefault(); toast.error('Fix what is listed first - the portal would refuse it.') } }}>Download for the portal</a></Button>}
        {e && draft && <Button variant="outline" onClick={() => setRecording('generated')}>Portal issued it...</Button>}
        {draft && <Button loading={save.isPending} disabled={!e && !f.to_key} onClick={() => save.mutate()}>Save</Button>}
        {!draft && <Button variant="ghost" onClick={onClose}>Close</Button>}
      </div>
      <PromptModal open={recording === 'generated'} title="The portal issued it" description="Record the number and date the portal gave." fields={[{ key: 'no', label: 'The twelve-digit e-way bill number', required: true }]} confirm="Record it" busy={act.isPending} error={act.error?.message} onSubmit={(v) => act.mutate({ path: 'generated', body: { ewb_no: v.no, ewb_date: today() } })} onClose={() => setRecording(null)} />
      <PromptModal open={recording === 'vehicle'} title="Change vehicle" description="As on the portal's Part B." fields={[{ key: 'no', label: 'The new vehicle number', required: true }, { key: 'why', label: 'Why did it change? (breakdown, transhipment...)' }]} confirm="Update the vehicle" busy={act.isPending} error={act.error?.message} onSubmit={(v) => act.mutate({ path: 'vehicle', body: { vehicle_no: v.no, reason: v.why } })} onClose={() => setRecording(null)} />
      <PromptModal open={recording === 'cancel'} title="Cancel the e-way bill" fields={[{ key: 'why', label: 'Why is it being cancelled?', required: true }]} confirm="Cancel it" busy={act.isPending} error={act.error?.message} onSubmit={(v) => act.mutate({ path: 'cancel', body: { reason: v.why } })} onClose={() => setRecording(null)} />
    </div>
  )
}
