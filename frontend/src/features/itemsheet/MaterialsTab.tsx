import { useMemo, useState } from 'react'
import { PackagePlus, Plus, Search, Trash2 } from 'lucide-react'
import { Button, Card, Field, Input, Modal, Select } from '@/components/ui'
import { addSheetItem, itemSheetKeys, saveItemSheet, type ItemSheet, type SheetBoqLine, type SheetGroup, type SheetMaterial } from '@/api/itemSheet'
import type { StoreItemOption } from '@/api/store'
import { ItemPicker } from '@/features/store/shared'
import { ApiError } from '@/lib/api'
import { formatQty, plural } from '@/lib/format'
import { useAction } from '@/lib/mutate'

const q = (v: number, unit: string) => (v ? `${formatQty(v)} ${unit}` : '-')
const lineLabel = (l: SheetBoqLine) => `${l.item_no ? `${l.item_no} ` : ''}${l.description}`

/** Which BOQ lines to show: one group or all, and lines whose text or materials match what is typed. */
export function useLineFilter(groups: SheetGroup[]) {
  const [group, setGroup] = useState('*')
  const [text, setText] = useState('')
  const shown = useMemo(() => {
    const t = text.trim().toLowerCase()
    return groups
      .filter((g) => group === '*' || g.code === group)
      .map((g) => ({ ...g, lines: g.lines.filter((l) => !t || `${l.item_no} ${l.description} ${l.materials.map((m) => `${m.item_code} ${m.item_name}`).join(' ')}`.toLowerCase().includes(t)) }))
      .filter((g) => g.lines.length > 0)
  }, [groups, group, text])
  const bar = (
    <div className="flex flex-wrap items-end gap-3">
      <Field label="Group" htmlFor="is-filter-group" className="w-44">
        <Select id="is-filter-group" value={group} onChange={(e) => setGroup(e.target.value)}
          options={[{ value: '*', label: 'All groups' }, ...groups.map((g) => ({ value: g.code, label: g.code || 'No group code' }))]} />
      </Field>
      <Field label="Find a BOQ line or material" htmlFor="is-filter-text" className="min-w-[14rem] flex-1">
        <Input id="is-filter-text" leading={<Search />} value={text} onChange={(e) => setText(e.target.value)} placeholder="Item no, work or material" />
      </Field>
    </div>
  )
  return { shown, bar }
}

/** The sheet as it stands: every BOQ line under its group code, and under each line its materials and how far they have got. */
export function MaterialsView({ s, onIndent }: { s: ItemSheet; onIndent?: (line: SheetBoqLine) => void }) {
  const { shown, bar } = useLineFilter(s.groups)
  return (
    <div className="space-y-4">
      {bar}
      {shown.length === 0 && <Card className="p-6 text-sm text-muted-foreground">No BOQ line matches.</Card>}
      {shown.map((g) => (
        <section key={g.code || '-'} aria-label={`Group ${g.code || 'with no code'}`} className="space-y-2">
          <h2 className="flex items-baseline gap-2 text-sm font-semibold">
            <span className="rounded-md bg-primary-soft px-2 py-0.5 font-mono text-primary">{g.code || 'No group code'}</span>
            <span className="font-normal text-muted-foreground">{plural(g.lines.length, 'BOQ line')}</span>
          </h2>
          {g.lines.map((l) => (
            <Card key={l.key} className="overflow-hidden">
              <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border bg-muted/40 px-4 py-2.5">
                <div className="min-w-0 text-sm">
                  <p className="font-medium">{lineLabel(l)}</p>
                  <p className="text-xs text-muted-foreground">BOQ {formatQty(l.qty)} {l.unit}{l.boq_item_code && <> · <span className="font-mono">{l.boq_item_code}</span></>}</p>
                </div>
                {onIndent && l.materials.length > 0 && <Button size="sm" variant="outline" onClick={() => onIndent(l)}>Ask for material</Button>}
              </div>
              {l.materials.length === 0 ? (
                <p className="px-4 py-3 text-sm text-muted-foreground">No materials yet.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm" aria-label={`Materials for ${lineLabel(l)}`}>
                    <thead className="text-xs uppercase tracking-wide text-muted-foreground">
                      <tr className="border-b border-border">
                        <th className="px-4 py-2 text-left font-medium">Material</th>
                        <th className="px-3 py-2 text-left font-medium max-sm:hidden">HSN</th>
                        <th className="px-3 py-2 text-right font-medium">Needed</th>
                        <th className="px-3 py-2 text-right font-medium max-md:hidden">Ordered</th>
                        <th className="px-3 py-2 text-right font-medium max-md:hidden">Received</th>
                        <th className="px-3 py-2 text-right font-medium max-lg:hidden">Indented</th>
                        <th className="px-3 py-2 text-right font-medium">Issued</th>
                      </tr>
                    </thead>
                    <tbody>
                      {l.materials.map((m) => <MaterialRow key={m.id} m={m} />)}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          ))}
        </section>
      ))}
      {s.orphans.length > 0 && (
        <Card className="space-y-2 p-4">
          <p className="text-sm font-medium text-warning">Under BOQ lines the BOQ no longer has</p>
          <p className="text-xs text-muted-foreground">These lines were taken out in a BOQ revision. Edit the sheet to move the materials to another line, or remove them.</p>
          <table className="w-full text-sm" aria-label="Materials under lines no longer on the BOQ"><tbody>{s.orphans.map((m) => <MaterialRow key={m.id} m={m} />)}</tbody></table>
        </Card>
      )}
    </div>
  )
}

function MaterialRow({ m }: { m: SheetMaterial }) {
  const over = m.issued > m.qty
  return (
    <tr className="border-b border-border last:border-0">
      <td className="px-4 py-2">
        <p>{m.item_name}</p>
        <p className="text-xs text-muted-foreground"><span className="font-mono">{m.item_code}</span>{m.remarks && ` · ${m.remarks}`}</p>
      </td>
      <td className="px-3 py-2 max-sm:hidden">{m.hsn || <span className="text-muted-foreground">-</span>}</td>
      <td className="px-3 py-2 text-right font-medium tabular">{q(m.qty, m.unit)}</td>
      <td className="px-3 py-2 text-right tabular max-md:hidden">{q(m.ordered, m.unit)}{m.awaiting > 0 && <p className="text-xs text-muted-foreground">{formatQty(m.awaiting)} awaiting approval</p>}</td>
      <td className="px-3 py-2 text-right tabular max-md:hidden">{q(m.received, m.unit)}</td>
      <td className="px-3 py-2 text-right tabular max-lg:hidden">{q(m.indented, m.unit)}</td>
      <td className={`px-3 py-2 text-right tabular ${over ? 'font-semibold text-danger' : ''}`}>{q(m.issued, m.unit)}</td>
    </tr>
  )
}

/** A material being edited: the item held whole so the box can show it without looking it up again. */
interface Draft { item: (StoreItemOption & { hsn?: string }) | null; qty: string; remarks: string; hsn: string }
const asDraft = (m: SheetMaterial): Draft => ({ item: { id: m.item_id, code: m.item_code, name: m.item_name, base_uom: m.unit, uoms: [], category: null }, qty: String(m.qty), remarks: m.remarks, hsn: m.hsn })
const blank = (): Draft => ({ item: null, qty: '', remarks: '', hsn: '' })

/** Making or changing the sheet: under each BOQ line, its materials from the item master (or new ones added to it), and how much. */
export function MaterialsEditor({ s, onDone, setProblems }: { s: ItemSheet; onDone: () => void; setProblems: (p: string[]) => void }) {
  const [drafts, setDrafts] = useState<Record<string, Draft[]>>(() => {
    const out: Record<string, Draft[]> = {}
    for (const g of s.groups) for (const l of g.lines) out[l.key] = l.materials.map(asDraft)
    return out
  })
  const [dropOrphans, setDropOrphans] = useState(false)
  const [adding, setAdding] = useState<{ key: string; index: number } | null>(null)
  const { shown, bar } = useLineFilter(s.groups)
  const set = (key: string, i: number, patch: Partial<Draft>) => setDrafts((d) => ({ ...d, [key]: d[key].map((x, n) => (n === i ? { ...x, ...patch } : x)) }))
  const addRow = (key: string) => setDrafts((d) => ({ ...d, [key]: [...(d[key] ?? []), blank()] }))
  const removeRow = (key: string, i: number) => setDrafts((d) => ({ ...d, [key]: d[key].filter((_, n) => n !== i) }))
  const count = Object.values(drafts).reduce((n, rows) => n + rows.filter((r) => r.item).length, 0)

  const rows = () => Object.entries(drafts).flatMap(([key, list]) => list.filter((r) => r.item || r.qty)
    .map((r) => ({ boq_key: key, item_code: r.item?.code ?? '', qty: r.qty === '' ? null : Number(r.qty), remarks: r.remarks })))
  // Taking off the materials of lines the BOQ no longer has is its own choice, saved with the rest.
  const save = useAction((drop: boolean) => saveItemSheet(s.job_id, rows(), drop), {
    invalidate: [itemSheetKeys.one(s.job_id), itemSheetKeys.all],
    success: (r) => (r.approved ? "Saved. It needs the Master's approval again; the approved sheet stays in force till then." : 'Saved. Send it to the Master for approval when it is complete.'),
    onSuccess: () => { setProblems([]); onDone() },
    onError: (e) => setProblems(e instanceof ApiError ? e.detail.split('\n').slice(1) : []),
  })

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <p className="text-sm text-muted-foreground">
          Under each BOQ line, add the store materials it needs: pick the item (its code, HSN and unit come from the Item Master) and the quantity in its unit. A material not in the Item Master yet can be added from here.
        </p>
        {bar}
      </Card>
      {shown.map((g) => (
        <section key={g.code || '-'} className="space-y-2" aria-label={`Group ${g.code || 'with no code'}`}>
          <h2 className="text-sm font-semibold"><span className="rounded-md bg-primary-soft px-2 py-0.5 font-mono text-primary">{g.code || 'No group code'}</span></h2>
          {g.lines.map((l) => (
            <Card key={l.key} className="space-y-3 p-4">
              <div className="text-sm">
                <p className="font-medium">{lineLabel(l)}</p>
                <p className="text-xs text-muted-foreground">BOQ {formatQty(l.qty)} {l.unit}</p>
              </div>
              {(drafts[l.key] ?? []).map((r, i) => (
                <div key={i} className="grid gap-2 rounded-lg border border-border p-3 md:grid-cols-[minmax(0,2fr)_8rem_minmax(0,1fr)_auto]">
                  <Field label="Material" htmlFor={`is-i-${l.key}-${i}`}>
                    <ItemPicker id={`is-i-${l.key}-${i}`} value={r.item} onChange={(item) => set(l.key, i, { item, hsn: '' })} />
                  </Field>
                  <Field label={`Quantity${r.item?.base_uom ? ` (${r.item.base_uom})` : ''}`} htmlFor={`is-q-${l.key}-${i}`}>
                    <Input id={`is-q-${l.key}-${i}`} inputMode="decimal" value={r.qty} onChange={(e) => set(l.key, i, { qty: e.target.value.replace(/[^\d.]/g, '') })} />
                  </Field>
                  <Field label="Remarks" htmlFor={`is-r-${l.key}-${i}`}><Input id={`is-r-${l.key}-${i}`} value={r.remarks} onChange={(e) => set(l.key, i, { remarks: e.target.value })} /></Field>
                  <div className="flex items-end justify-between gap-2">
                    {r.hsn && <span className="pb-2 text-xs text-muted-foreground">HSN {r.hsn}</span>}
                    <Button variant="ghost" size="icon" aria-label={`Remove material ${i + 1} of ${lineLabel(l)}`} onClick={() => removeRow(l.key, i)}><Trash2 /></Button>
                  </div>
                  {!r.item && <button type="button" className="text-left text-xs font-medium text-primary hover:underline md:col-span-4" onClick={() => setAdding({ key: l.key, index: i })}>Not in the Item Master? Add it</button>}
                </div>
              ))}
              <Button size="sm" variant="outline" onClick={() => addRow(l.key)}><Plus /> Add material</Button>
            </Card>
          ))}
        </section>
      ))}
      {s.orphans.length > 0 && (
        <Card className="space-y-2 p-4 text-sm">
          <p className="font-medium text-warning">{plural(s.orphans.length, 'material')} under BOQ lines the BOQ no longer has</p>
          <p className="text-muted-foreground">{s.orphans.map((m) => `${m.item_name} (${formatQty(m.qty)} ${m.unit})`).join(', ')}. They stay on the sheet unless you take them off.</p>
          <label className="flex items-center gap-2"><input type="checkbox" checked={dropOrphans} onChange={(e) => setDropOrphans(e.target.checked)} /> Take them off when I save</label>
        </Card>
      )}
      <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-end gap-2 border-t border-border bg-background/95 py-3 backdrop-blur">
        <span className="mr-auto text-sm text-muted-foreground">{plural(count, 'material')} on the sheet</span>
        <Button variant="ghost" onClick={() => { setProblems([]); onDone() }}>Cancel</Button>
        <Button onClick={() => save.mutate(dropOrphans)} loading={save.isPending}>Save</Button>
      </div>
      {adding && (
        <NewItemModal job={s.job_id} units={s.units} onClose={() => setAdding(null)}
          onAdded={(item) => { set(adding.key, adding.index, { item, hsn: item.hsn ?? '' }); setAdding(null) }} />
      )}
    </div>
  )
}

/** A store material added to the Item Master from the sheet: it gets the next item code. */
function NewItemModal({ job, units, onClose, onAdded }: { job: number; units: string[]; onClose: () => void; onAdded: (item: StoreItemOption & { hsn: string }) => void }) {
  const [f, setF] = useState({ item_name: '', units_of_measure: '', hsn_code: '', make: '' })
  const add = useAction(() => addSheetItem(job, f), { onSuccess: (r) => onAdded(r.item) })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Add a material to the Item Master" description="It is added as a store material with the next item code, and put on this line."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={() => add.mutate()} loading={add.isPending} disabled={!f.item_name.trim() || !f.units_of_measure}><PackagePlus /> Add</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" htmlFor="ni-name" className="sm:col-span-2"><Input id="ni-name" value={f.item_name} onChange={(e) => setF({ ...f, item_name: e.target.value })} placeholder="Cement OPC 53 grade" /></Field>
        <Field label="Unit" htmlFor="ni-unit"><Select id="ni-unit" placeholder="Choose" value={f.units_of_measure} onChange={(e) => setF({ ...f, units_of_measure: e.target.value })} options={units.map((u) => ({ value: u, label: u }))} /></Field>
        <Field label="HSN" htmlFor="ni-hsn"><Input id="ni-hsn" value={f.hsn_code} onChange={(e) => setF({ ...f, hsn_code: e.target.value })} placeholder="2523" /></Field>
        <Field label="Make (optional)" htmlFor="ni-make" className="sm:col-span-2"><Input id="ni-make" value={f.make} onChange={(e) => setF({ ...f, make: e.target.value })} placeholder="UltraTech" /></Field>
      </div>
    </Modal>
  )
}
