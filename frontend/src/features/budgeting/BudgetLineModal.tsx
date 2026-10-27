import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { budgetKey, budgetMaterials, COST_KINDS, pct, saveBudgetLine, type BudgetItem, type BudgetRow, type CostKind, type MaterialOption } from '@/api/budgeting'
import { useAction } from '@/lib/mutate'
import { useDebounced } from '@/lib/hooks'
import { formatINR, cn } from '@/lib/utils'

const blank = (kind: CostKind): BudgetItem => ({ kind, description: '', uom: '', coefficient: 1, rate: 0, item_code: '' })

/** What one BOQ line costs us: the materials, the labour and the rest that go into one unit of it, against the client's rate. */
export function BudgetLineModal({ job, row, overhead, contingency, onClose }: { job: number; row: BudgetRow; overhead: number; contingency: number; onClose: () => void }) {
  const [items, setItems] = useState<BudgetItem[]>(() => (row.items.length ? row.items.map((i) => ({ ...i })) : [blank('MATERIAL'), blank('LABOUR')]))
  const [search, setSearch] = useState('')
  const q = useDebounced(search)
  const [options, setOptions] = useState<MaterialOption[]>([])
  useEffect(() => {
    let live = true
    if (q.trim().length >= 2) budgetMaterials(q.trim()).then((r) => live && setOptions(r)).catch(() => live && setOptions([]))
    else setOptions([])
    return () => { live = false }
  }, [q])

  const set = (n: number, patch: Partial<BudgetItem>) => setItems((all) => all.map((it, i) => (i === n ? { ...it, ...patch } : it)))
  // A material picked from the item master brings its unit and the rate we last paid; both stay editable.
  const describe = (n: number, text: string) => {
    const hit = items[n].kind === 'MATERIAL' ? options.find((o) => `${o.name} (${o.code})` === text) : undefined
    if (hit) set(n, { description: hit.name, item_code: hit.code, uom: hit.uom, rate: hit.rate || items[n].rate })
    else { set(n, { description: text, item_code: '' }); setSearch(text) }
  }

  const unit = (k: CostKind) => items.filter((i) => i.kind === k).reduce((s, i) => s + i.coefficient * i.rate, 0)
  const perUnit = unit('MATERIAL') + unit('LABOUR') + unit('OTHER')
  const direct = perUnit * row.quantity
  const cost = direct * (1 + (overhead + contingency) / 100)
  const profit = row.revenue - cost
  // A starter row left untouched (a quantity of 1 and nothing else) is not a cost.
  const filled = items.filter((i) => i.description.trim() || i.rate)
  const used = filled.length > 0

  const save = useAction(() => saveBudgetLine(job, row.key, filled), { invalidate: [budgetKey(job)], success: 'Line budget saved', onSuccess: onClose })

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title={`Budget: ${row.item_no ? row.item_no + ' ' : ''}${row.description}`}
      description={`${row.quantity} ${row.uom} at the client's ${formatINR(row.rate)} per ${row.uom || 'unit'} = ${formatINR(row.revenue)}. Enter what ONE ${row.uom || 'unit'} costs us.`}
      footer={<><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>{used ? 'Save' : 'Remove from budget'}</Button></>}>
      <datalist id="budget-materials">{options.map((o) => <option key={o.code} value={`${o.name} (${o.code})`} />)}</datalist>
      <dl className="mb-4 grid grid-cols-2 gap-3 rounded-md border border-border bg-primary-soft/40 p-3 text-sm sm:grid-cols-4">
        <Sum label="BOQ quantity" value={`${row.quantity} ${row.uom}`} />
        <Sum label={`BOQ rate per ${row.uom || 'unit'}`} value={formatINR(row.rate)} strong />
        <Sum label="BOQ amount (client pays)" value={row.rate_only ? 'Rate only' : formatINR(row.revenue)} strong />
        <Sum label="Our cost vs BOQ rate" value={used && row.rate ? pct((perUnit / row.rate) * 100) + ' of the rate' : '-'} />
      </dl>
      <div className="space-y-2">
        <div className="hidden grid-cols-[8rem_1fr_5rem_6rem_7rem_7rem_2rem] gap-2 text-xs text-muted-foreground md:grid">
          <span>Type</span><span>What</span><span>Unit</span><span className="text-right">Qty per {row.uom || 'unit'}</span><span className="text-right">Rate</span><span className="text-right">Cost per {row.uom || 'unit'}</span><span />
        </div>
        {items.map((it, n) => (
          <div key={n} className="grid grid-cols-2 items-center gap-2 rounded-md border border-border p-2 md:grid-cols-[8rem_1fr_5rem_6rem_7rem_7rem_2rem] md:border-0 md:p-0">
            <Select aria-label="Type" value={it.kind} options={COST_KINDS} onChange={(e) => set(n, { kind: e.target.value as CostKind })} />
            <Input aria-label="What" list={it.kind === 'MATERIAL' ? 'budget-materials' : undefined} className="col-span-2 md:col-span-1" placeholder={it.kind === 'MATERIAL' ? 'Cement, sand, steel...' : it.kind === 'LABOUR' ? 'Mason, helper, bar bender...' : 'Machine hire, sub-contract...'}
              value={it.description} onChange={(e) => describe(n, e.target.value)} />
            <Input aria-label="Unit" placeholder={it.kind === 'LABOUR' ? 'day' : 'unit'} value={it.uom} onChange={(e) => set(n, { uom: e.target.value })} />
            <NumField aria-label="Quantity per unit" value={it.coefficient} onValue={(v) => set(n, { coefficient: v })} />
            <NumField aria-label="Rate" value={it.rate} onValue={(v) => set(n, { rate: v })} />
            <p className="tabular text-right text-sm">{formatINR(it.coefficient * it.rate)}</p>
            <Button variant="ghost" size="icon-sm" aria-label="Remove" onClick={() => setItems((all) => all.filter((_, i) => i !== n))}><Trash2 /></Button>
          </div>
        ))}
        <div className="flex flex-wrap gap-2 pt-1">
          {COST_KINDS.map((k) => <Button key={k.value} variant="outline" size="sm" onClick={() => setItems((all) => [...all, blank(k.value)])}><Plus /> {k.label}</Button>)}
        </div>
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-3 rounded-md bg-muted/50 p-3 text-sm sm:grid-cols-4">
        <Sum label="Material per unit" value={formatINR(unit('MATERIAL'))} />
        <Sum label="Labour per unit" value={formatINR(unit('LABOUR'))} />
        <Sum label="Plant & other per unit" value={formatINR(unit('OTHER'))} />
        <Sum label="Our cost per unit" value={formatINR(perUnit)} strong />
        <Sum label="Client pays per unit" value={formatINR(row.rate)} />
        <Sum label={`Cost for ${row.quantity} ${row.uom}${overhead || contingency ? ' with overheads' : ''}`} value={formatINR(cost)} />
        <Sum label="Profit on this line" value={used ? formatINR(profit) : '-'} strong tone={used ? (profit < 0 ? 'danger' : 'success') : undefined} />
        <Sum label="Margin" value={used && row.revenue ? pct((profit / row.revenue) * 100) : '-'} tone={used ? (profit < 0 ? 'danger' : 'success') : undefined} />
      </dl>
      {!row.quantity && <Field label="" hint="This line has no quantity in the BOQ yet, so its cost and profit show as nothing until it has one." className="mt-2"><span /></Field>}
    </Modal>
  )
}

function Sum({ label, value, strong, tone }: { label: string; value: string; strong?: boolean; tone?: 'success' | 'danger' }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('tabular', strong && 'font-semibold', tone === 'danger' && 'text-danger', tone === 'success' && 'text-success')}>{value}</dd>
    </div>
  )
}
