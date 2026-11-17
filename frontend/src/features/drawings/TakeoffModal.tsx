import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Download, ListPlus, Send } from 'lucide-react'
import { Badge, Button, Field, Modal, NumField, Select, Skeleton } from '@/components/ui'
import { drawingTakeoff, takeoffToBoq, takeoffToEnquiry, type Drawing, type Takeoff, type TakeoffSendLine } from '@/api/drawings'
import { ApiError } from '@/lib/api'
import { useSession } from '@/lib/session'
import { downloadCsv } from '@/lib/utils'

type Material = Takeoff['materials'][number]
// Work a client is billed for, measured off the sheet: what goes to the BOQ unless unticked.
const BOQ_WORK = new Set(['Wall length', 'Wall area, openings taken off', 'Masonry', 'Plaster area', 'Floor area', 'Concrete', 'Shuttering', 'Floor tiles', 'Doors', 'Windows'])
// Measurements, not things bought: never on an enquiry.
const NOT_BOUGHT = new Set(['Wall length', 'Wall area, openings taken off', 'Masonry', 'Plaster area', 'Floor area'])

const KINDS = [{ value: 'wall', label: 'Wall' }, { value: 'slab', label: 'Floor / slab' }, { value: 'door', label: 'Door' }, { value: 'window', label: 'Window' }, { value: 'ignore', label: 'Ignore' }]
const SETTINGS: [string, string][] = [
  ['storeys', 'Floors'], ['wall_height_m', 'Wall height (m)'], ['wall_thickness_m', 'Wall thickness (m)'], ['slab_thickness_m', 'Slab thickness (m)'],
  ['bricks_per_cum', 'Bricks a cum'], ['steel_kg_per_cum', 'Steel kg a cum'], ['wastage_percent', 'Wastage %'],
]

/** What the sheet measures and the material that takes: exact from a DXF, an estimate from a picture. Nothing is saved. */
export function TakeoffModal({ drawing, onClose }: { drawing: Drawing | null; onClose: () => void }) {
  return (
    <Modal open={!!drawing} onOpenChange={(o) => !o && onClose()} size="xl" title={drawing ? `Quantities: ${drawing.number}` : ''} description="What this sheet measures, and the material that takes. Change any figure and it works out again.">
      {drawing && <Body key={drawing.id} id={drawing.id} number={drawing.number} />}
    </Modal>
  )
}

function Body({ id, number }: { id: number; number: string }) {
  const [t, setT] = useState<Takeoff | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [assumptions, setAssumptions] = useState<Record<string, number>>({})
  const [kinds, setKinds] = useState<Record<string, string>>({})
  const [width, setWidth] = useState(0)
  const [sending, setSending] = useState<'boq' | 'enquiry' | null>(null)
  const { can } = useSession()
  useEffect(() => {
    let live = true
    setBusy(true)
    const wait = setTimeout(() => {
      drawingTakeoff(id, { assumptions, kinds, width_m: width || undefined })
        .then((r) => { if (live) { setT(r); setError('') } })
        .catch((e: Error) => { if (live) setError(e.message) })
        .finally(() => { if (live) setBusy(false) })
    }, 350)
    return () => { live = false; clearTimeout(wait) }
  }, [id, assumptions, kinds, width])
  const groups = useMemo(() => {
    const m = new Map<string, Takeoff['materials']>()
    for (const l of t?.materials ?? []) m.set(l.group, [...(m.get(l.group) ?? []), l])
    return [...m.entries()]
  }, [t])
  if (error) return <p role="alert" className="rounded-lg border border-danger/30 bg-danger-soft p-3 text-sm">{error}</p>
  if (!t) return <Skeleton className="h-64 w-full" />
  const a = { ...t.assumptions, ...assumptions }
  return (
    <div className="grid gap-5">
      <p className="flex flex-wrap items-center gap-2 text-sm">
        {t.exact ? <Badge tone="success">Exact, from AutoCAD{t.converted_from ? ` (${t.converted_from} read as DXF)` : ''}</Badge> : <Badge tone="warning">Estimate, from a picture</Badge>}
        <span className="text-muted-foreground">{t.drawing}, revision {t.revision}.{t.units ? ` Drawn in ${t.units}.` : ''}</span>
      </p>
      {!t.exact && <p className="rounded-lg border border-warning/40 bg-warning-soft p-3 text-[13px]">Read off the picture, so use it for an early idea and not for ordering. For exact figures add the DXF from AutoCAD as a new revision.{t.low_confidence ? ' This sheet was hard to read: treat these figures with extra care.' : ''}</p>}
      {t.exact && !t.units_stated && <p className="rounded-lg border border-warning/40 bg-warning-soft p-3 text-[13px]">The file does not say what units it was drawn in, so millimetres are assumed. Check one wall length below against the drawing.</p>}
      {!t.exact && (
        <Field label="Real width of the whole plan (metres)" htmlFor="to-width" hint={t.needs_width ? 'The width could not be read off the sheet. Enter it to get quantities.' : 'Read off the sheet. Correct it if it is wrong: everything scales from it.'} className="max-w-xs">
          <NumField id="to-width" value={width || t.width_m || 0} onValue={setWidth} />
        </Field>
      )}
      {t.layers.length > 0 && (
        <details open={!t.quantities.wall_m}>
          <summary className="cursor-pointer text-sm font-medium">What each layer holds ({t.layers.length})</summary>
          <p className="mb-2 mt-1 text-[13px] text-muted-foreground">Guessed from the layer names. Correct any that are wrong.</p>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground"><tr><th className="pb-2">Layer</th><th className="pb-2 text-right">Length (m)</th><th className="pb-2 text-right">Area (sqm)</th><th className="pb-2 text-right">Blocks</th><th className="pb-2 pl-4">Is</th></tr></thead>
            <tbody>
              {t.layers.map((l) => (
                <tr key={l.name} className="border-t border-border">
                  <td className="py-1 font-mono text-[13px]">{l.name}</td>
                  <td className="text-right tabular-nums">{l.length_m || ''}</td>
                  <td className="text-right tabular-nums">{l.area_sqm || ''}</td>
                  <td className="text-right tabular-nums">{l.blocks || ''}</td>
                  <td className="w-40 py-1 pl-4"><Select aria-label={`What ${l.name} holds`} value={kinds[l.name] ?? l.kind} onChange={(e) => setKinds((k) => ({ ...k, [l.name]: e.target.value }))} options={KINDS} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <label className="mt-2 flex items-center gap-2 text-[13px]"><input type="checkbox" checked={!!a.double_line_walls} onChange={(e) => setAssumptions((x) => ({ ...x, double_line_walls: e.target.checked ? 1 : 0 }))} /> Walls are drawn as two lines, one for each face</label>
        </details>
      )}
      <div className="grid gap-3 sm:grid-cols-4">
        {SETTINGS.map(([key, label]) => <Field key={key} label={label} htmlFor={`to-${key}`}><NumField id={`to-${key}`} value={a[key] ?? 0} onValue={(n) => setAssumptions((x) => ({ ...x, [key]: n }))} /></Field>)}
      </div>
      {groups.length === 0 ? <p className="text-sm text-muted-foreground">{t.needs_width ? 'Enter the real width above.' : 'Nothing measured yet. Say which layers are walls and floors.'}</p> : (
        <div className={busy ? 'opacity-60' : undefined}>
          <table className="w-full text-sm" aria-label="Material take-off">
            <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground"><tr><th className="pb-2">Item</th><th className="pb-2 text-right">Quantity</th><th className="pb-2 pl-2">Unit</th><th className="pb-2 pl-4">How</th></tr></thead>
            {groups.map(([group, rows]) => (
              <tbody key={group}>
                <tr><td colSpan={4} className="pt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{group}</td></tr>
                {rows.map((r) => <tr key={r.item} className="border-t border-border"><td className="py-1.5 font-medium">{r.item}</td><td className="text-right tabular-nums">{r.quantity.toLocaleString('en-IN')}</td><td className="pl-2">{r.uom}</td><td className="pl-4 text-[13px] text-muted-foreground">{r.how}</td></tr>)}
              </tbody>
            ))}
          </table>
          <p className="mt-3 text-xs text-muted-foreground">Rules of thumb, for planning and enquiries. Columns, beams and footings are not on a plan and are left out; have your engineer check before ordering.</p>
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <Button variant="outline" onClick={() => downloadCsv(`takeoff-${number}`, ['Group', 'Item', 'Quantity', 'Unit', 'How'], t.materials.map((m) => [m.group, m.item, m.quantity, m.uom, m.how]))}><Download /> Download</Button>
            {can('workorders.manage') && <Button variant="outline" onClick={() => setSending('boq')}><ListPlus /> Send to BOQ lines</Button>}
            {can('purchase.manage') && <Button onClick={() => setSending('enquiry')}><Send /> Raise enquiry</Button>}
          </div>
          {sending && <SendPanel key={sending} to={sending} id={id} materials={t.materials} exact={t.exact} onDone={() => setSending(null)} />}
        </div>
      )}
    </div>
  )
}

/** The lines to send on, ticked by what usually goes there: the work measured to the BOQ, the materials to an enquiry
 * (the same material from several parts asked for once). Each can be unticked before it goes. */
function SendPanel({ to, id, materials, exact, onDone }: { to: 'boq' | 'enquiry'; id: number; materials: Material[]; exact: boolean; onDone: () => void }) {
  const rows = useMemo(() => {
    if (to === 'boq') return materials.map((m) => ({ key: `${m.group}|${m.item}`, description: m.group === 'Quantities' || m.group === 'Openings' ? m.item : `${m.group} - ${m.item}`, uom: m.uom, quantity: m.quantity, on: BOQ_WORK.has(m.item) }))
    const merged = new Map<string, { key: string; description: string; uom: string; quantity: number; on: boolean }>()
    for (const m of materials.filter((x) => !NOT_BOUGHT.has(x.item))) {
      const key = `${m.item.toLowerCase()}|${m.uom.toLowerCase()}`
      const had = merged.get(key)
      merged.set(key, had ? { ...had, quantity: Math.round((had.quantity + m.quantity) * 100) / 100 } : { key, description: m.item, uom: m.uom, quantity: m.quantity, on: true })
    }
    return [...merged.values()]
  }, [to, materials])
  const [on, setOn] = useState<Record<string, boolean>>(() => Object.fromEntries(rows.map((r) => [r.key, r.on])))
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<{ text: string; link?: string; label?: string } | null>(null)
  const [error, setError] = useState('')
  const picked: TakeoffSendLine[] = rows.filter((r) => on[r.key] && r.quantity > 0).map(({ description, uom, quantity }) => ({ description, uom, quantity }))
  const send = async () => {
    setBusy(true)
    setError('')
    try {
      if (to === 'boq') {
        const r = await takeoffToBoq(id, picked)
        setDone({ text: r.message, link: `/projects/boq/${r.boq_id}`, label: 'Open the BOQ' })
      } else {
        const r = await takeoffToEnquiry(id, picked)
        setDone({ text: r.message, link: `/store/enquiries/${r.rfq.id}`, label: `Open ${r.rfq.number}` })
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Not sent.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <section aria-label={to === 'boq' ? 'Send to BOQ lines' : 'Raise enquiry'} className="mt-4 rounded-lg border border-border bg-surface/50 p-3">
      <h3 className="text-sm font-semibold">{to === 'boq' ? 'Add to the project BOQ' : 'Ask suppliers for these materials'}</h3>
      <p className="mt-0.5 text-[13px] text-muted-foreground">{to === 'boq' ? 'Added at the end of the BOQ under a heading naming this drawing and revision, without rates: price them in the BOQ.' : 'A new enquiry on this project. Add the suppliers to ask from the enquiry.'}{!exact && ' These are estimates from a picture: check them first.'}</p>
      {done ? (
        <p role="status" className="mt-3 text-sm">{done.text} {done.link && <Link className="font-medium text-primary underline underline-offset-2" to={done.link}>{done.label}</Link>}</p>
      ) : (
        <>
          <ul className="mt-3 grid gap-1 text-sm">
            {rows.map((r) => (
              <li key={r.key}><label className="flex items-center gap-2"><input type="checkbox" checked={!!on[r.key]} onChange={(e) => setOn((o) => ({ ...o, [r.key]: e.target.checked }))} /><span className="flex-1">{r.description}</span><span className="tabular-nums">{r.quantity.toLocaleString('en-IN')} {r.uom}</span></label></li>
            ))}
          </ul>
          {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" onClick={onDone}>Cancel</Button>
            <Button loading={busy} disabled={!picked.length} onClick={() => void send()}>{to === 'boq' ? `Add ${picked.length} line${picked.length === 1 ? '' : 's'} to the BOQ` : `Raise enquiry for ${picked.length} item${picked.length === 1 ? '' : 's'}`}</Button>
          </div>
        </>
      )}
    </section>
  )
}
