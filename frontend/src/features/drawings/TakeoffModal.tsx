import { useEffect, useMemo, useState } from 'react'
import { Download } from 'lucide-react'
import { Badge, Button, Field, Modal, NumField, Select, Skeleton } from '@/components/ui'
import { drawingTakeoff, type Drawing, type Takeoff } from '@/api/drawings'
import { downloadCsv } from '@/lib/utils'

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
        {t.exact ? <Badge tone="success">Exact, from AutoCAD</Badge> : <Badge tone="warning">Estimate, from a picture</Badge>}
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
          <div className="mt-3 flex justify-end"><Button variant="outline" onClick={() => downloadCsv(`takeoff-${number}`, ['Group', 'Item', 'Quantity', 'Unit', 'How'], t.materials.map((m) => [m.group, m.item, m.quantity, m.uom, m.how]))}><Download /> Download</Button></div>
        </div>
      )}
    </div>
  )
}
