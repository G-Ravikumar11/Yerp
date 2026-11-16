import { useEffect, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { AlertTriangle, Plus, Trash2 } from 'lucide-react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { budgetKey, budgetMaterials, COST_KINDS, pct, resolveBudgetWastage, saveBudgetLine, type BudgetItem, type BudgetRow, type CostKind, type MaterialOption, type WastageAnswer } from '@/api/budgeting'
import { useAction } from '@/lib/mutate'
import { useDebounced } from '@/lib/hooks'
import { formatINR, cn, formatRate } from '@/lib/utils'

const blank = (kind: CostKind): BudgetItem => ({ kind, description: '', uom: '', coefficient: 1, rate: 0, item_code: '', wastage_percent: 0 })
const own = (i: BudgetItem) => (i.kind === 'MATERIAL' ? i.wastage_percent ?? 0 : 0)
/** What the server is asked about an item: enough to find its norm and compare it with the budget's own figure. */
const asked = (i: BudgetItem) => ({ kind: i.kind, item_code: i.item_code, wastage_percent: own(i) })
const qty = (v: number) => v.toLocaleString('en-IN', { maximumFractionDigits: 3 })
const percent = (v: number) => `${Math.round(v * 1000) / 1000}%`

/** What one BOQ line costs us: the materials, the labour and the rest that go into one unit of it, against the client's rate. */
export function BudgetLineModal({ job, row, overhead, contingency, onClose }: { job: number; row: BudgetRow; overhead: number; contingency: number; onClose: () => void }) {
  const [items, setItems] = useState<BudgetItem[]>(() => (row.items.length ? row.items.map((i) => ({ ...i, wastage_percent: i.wastage_percent ?? 0 })) : [blank('MATERIAL'), blank('LABOUR')]))
  const [search, setSearch] = useState('')
  const q = useDebounced(search)
  const [options, setOptions] = useState<MaterialOption[]>([])
  useEffect(() => {
    let live = true
    if (q.trim().length >= 2) budgetMaterials(q.trim()).then((r) => live && setOptions(r)).catch(() => live && setOptions([]))
    else setOptions([])
    return () => { live = false }
  }, [q])

  // Which wastage % each material is costed at is the server's answer - the store's norm where one is set, else the figure
  // typed here - asked again whenever a material or its figure changes. This screen never chooses between the two itself.
  const asking = useDebounced(JSON.stringify(items.map(asked)))
  const answers = useQuery({
    queryKey: [...budgetKey(job), 'wastage', row.key, asking],
    queryFn: async () => { const sent = JSON.parse(asking) as ReturnType<typeof asked>[]; return { sent, got: await resolveBudgetWastage(job, row.key, sent) } },
    placeholderData: keepPreviousData,
    staleTime: 0,
  })
  /** The server's answer for item n, when it is an answer to the item as it stands now; else nothing yet. */
  const answer = (n: number): WastageAnswer | null => {
    const it = items[n]
    if (it.kind !== 'MATERIAL') return null
    const sent = answers.data?.sent[n]
    return sent && sent.kind === it.kind && sent.item_code === it.item_code && sent.wastage_percent === own(it) ? answers.data!.got[n] ?? null : null
  }

  const set = (n: number, patch: Partial<BudgetItem>) => setItems((all) => all.map((it, i) => (i === n ? { ...it, ...patch } : it)))
  // A material picked from the item master brings its unit and the rate we last paid; both stay editable.
  const describe = (n: number, text: string) => {
    const hit = items[n].kind === 'MATERIAL' ? options.find((o) => `${o.name} (${o.code})` === text) : undefined
    if (hit) set(n, { description: hit.name, item_code: hit.code, uom: hit.uom, rate: hit.rate || items[n].rate })
    else { set(n, { description: text, item_code: '' }); setSearch(text) }
  }

  // A material's cost carries its wastage once, at the percentage the server gave.
  const each = (n: number) => items[n].coefficient * items[n].rate * (1 + (answer(n)?.effective_wastage_percent ?? 0) / 100)
  const unit = (k: CostKind) => items.reduce((s, i, n) => (i.kind === k ? s + each(n) : s), 0)
  const perUnit = unit('MATERIAL') + unit('LABOUR') + unit('OTHER')
  const direct = perUnit * row.quantity
  const cost = direct * (1 + (overhead + contingency) / 100)
  const profit = row.revenue - cost
  // A starter row left untouched (a quantity of 1 and nothing else) is not a cost.
  const filled = items.filter((i) => i.description.trim() || i.rate)
  const used = filled.length > 0
  const mismatches = items.map((it, n) => ({ it, a: answer(n) })).filter((x) => x.a?.has_wastage_mismatch)

  const save = useAction(() => saveBudgetLine(job, row.key, filled.map((i) => ({ kind: i.kind, description: i.description, uom: i.uom, coefficient: i.coefficient, rate: i.rate, item_code: i.item_code, wastage_percent: own(i) }))),
    { invalidate: [budgetKey(job)], success: 'Line budget saved', onSuccess: onClose })

  const grid = 'md:grid-cols-[8rem_1fr_5rem_6rem_7rem_5.5rem_7rem_2rem]'
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title={`Budget: ${row.item_no ? row.item_no + ' ' : ''}${row.description}`}
      description={`${row.quantity} ${row.uom} at the client's ${formatRate(row.rate)} per ${row.uom || 'unit'} = ${formatINR(row.revenue)}. Enter what ONE ${row.uom || 'unit'} costs us.`}
      footer={<><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>{used ? 'Save' : 'Remove from budget'}</Button></>}>
      <datalist id="budget-materials">{options.map((o) => <option key={o.code} value={`${o.name} (${o.code})`} />)}</datalist>
      <dl className="mb-4 grid grid-cols-2 gap-3 rounded-md border border-border bg-primary-soft/40 p-3 text-sm sm:grid-cols-4">
        <Sum label="BOQ quantity" value={`${row.quantity} ${row.uom}`} />
        <Sum label={`BOQ rate per ${row.uom || 'unit'}`} value={formatRate(row.rate)} strong />
        <Sum label="BOQ amount (client pays)" value={row.rate_only ? 'Rate only' : formatINR(row.revenue)} strong />
        <Sum label="Our cost vs BOQ rate" value={used && row.rate ? pct((perUnit / row.rate) * 100) + ' of the rate' : '-'} />
      </dl>
      {mismatches.length > 0 && (
        <div role="alert" className="mb-4 rounded-md border border-warning/40 bg-warning-soft p-3 text-sm">
          <p className="flex items-center gap-2 font-semibold text-warning"><AlertTriangle className="size-4" aria-hidden /> Wastage Percentage Mismatch</p>
          <ul className="mt-1.5 space-y-1.5">
            {mismatches.map(({ it, a }, i) => (
              <li key={i}>
                <span className="font-medium">{it.description || 'Material'}</span>: Budgeting Wastage: {percent(a!.budgeting_wastage_percent)} · Store Norm Wastage: {percent(a!.store_norm_wastage_percent ?? 0)}.{' '}
                The Store Norm wastage percentage ({percent(a!.effective_wastage_percent)}) is being used for Budgeting calculations.
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="space-y-2">
        <div className={cn('hidden gap-2 text-xs text-muted-foreground md:grid', grid)}>
          <span>Type</span><span>What</span><span>Unit</span><span className="text-right">Qty per {row.uom || 'unit'}</span><span className="text-right">Rate</span><span className="text-right">Wastage %</span><span className="text-right">Cost per {row.uom || 'unit'}</span><span />
        </div>
        {items.map((it, n) => {
          const a = answer(n)
          const base = row.quantity * it.coefficient
          const waste = a ? (base * a.effective_wastage_percent) / 100 : 0
          return (
            <div key={n} className={cn('grid grid-cols-2 items-center gap-2 rounded-md border border-border p-2 md:border-0 md:p-0', grid)}>
              <Select aria-label="Type" value={it.kind} options={COST_KINDS} onChange={(e) => set(n, { kind: e.target.value as CostKind })} />
              <Input aria-label="What" list={it.kind === 'MATERIAL' ? 'budget-materials' : undefined} className="col-span-2 md:col-span-1" placeholder={it.kind === 'MATERIAL' ? 'Cement, sand, steel...' : it.kind === 'LABOUR' ? 'Mason, helper, bar bender...' : 'Machine hire, sub-contract...'}
                value={it.description} onChange={(e) => describe(n, e.target.value)} />
              <Input aria-label="Unit" placeholder={it.kind === 'LABOUR' ? 'day' : 'unit'} value={it.uom} onChange={(e) => set(n, { uom: e.target.value })} />
              <NumField aria-label="Quantity per unit" value={it.coefficient} onValue={(v) => set(n, { coefficient: v })} />
              <NumField aria-label="Rate" value={it.rate} onValue={(v) => set(n, { rate: v })} />
              {it.kind === 'MATERIAL'
                ? <NumField aria-label="Budgeting wastage %" title="The budget's own wastage %. Used only where the store has no norm for this material on this BOQ item." value={it.wastage_percent ?? 0} onValue={(v) => set(n, { wastage_percent: Math.min(100, Math.max(0, v || 0)) })} />
                : <span className="text-right text-xs text-muted-foreground max-md:hidden">-</span>}
              <p className="tabular text-right text-sm">{it.kind === 'MATERIAL' && !a ? '...' : formatINR(each(n))}</p>
              <Button variant="ghost" size="icon-sm" aria-label="Remove" onClick={() => setItems((all) => all.filter((_, i) => i !== n))}><Trash2 /></Button>
              {it.kind === 'MATERIAL' && a && (it.description.trim() || it.rate > 0) && (
                <div className={cn('col-span-full -mt-1 rounded px-2 py-1 text-xs', a.has_wastage_mismatch ? 'bg-warning-soft text-foreground' : 'bg-muted/50 text-muted-foreground')} data-testid="wastage-detail">
                  <p>
                    Budgeting Wastage: {percent(a.budgeting_wastage_percent)} · Store Norm Wastage: {a.store_norm_wastage_percent == null ? 'not configured' : percent(a.store_norm_wastage_percent)} ·{' '}
                    <strong className="font-semibold text-foreground">Effective Wastage Used: {percent(a.effective_wastage_percent)}</strong> ({a.wastage_source === 'STORE_NORM' ? 'Store Norm' : 'Budgeting'})
                  </p>
                  {a.wastage_source === 'BUDGETING' && <p>Store Material Norm not configured. Budgeting wastage percentage is being used.</p>}
                  {row.quantity > 0 && it.coefficient > 0 && (
                    <p className="tabular">Base Material Quantity: {qty(base)} {it.uom} · Wastage Quantity: {qty(waste)} {it.uom} · Final Required Quantity: {qty(base + waste)} {it.uom}</p>
                  )}
                </div>
              )}
            </div>
          )
        })}
        <div className="flex flex-wrap gap-2 pt-1">
          {COST_KINDS.map((k) => <Button key={k.value} variant="outline" size="sm" onClick={() => setItems((all) => [...all, blank(k.value)])}><Plus /> {k.label}</Button>)}
        </div>
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-3 rounded-md bg-muted/50 p-3 text-sm sm:grid-cols-4">
        <Sum label="Material per unit (with wastage)" value={formatINR(unit('MATERIAL'))} />
        <Sum label="Labour per unit" value={formatINR(unit('LABOUR'))} />
        <Sum label="Plant & other per unit" value={formatINR(unit('OTHER'))} />
        <Sum label="Our cost per unit" value={formatINR(perUnit)} strong />
        <Sum label="Client pays per unit" value={formatRate(row.rate)} />
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
