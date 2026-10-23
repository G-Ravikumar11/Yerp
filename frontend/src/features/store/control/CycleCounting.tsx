import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Badge, Button, Field, Input } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { get, post, put } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { storePerm } from '@/api/store'
import { StorePicker } from '../shared'
import { dmy, money, num } from './api'

interface Due { store_id: number; store_code: string; item_id: number; item_code: string; item_name: string; base_uom: string; class: 'A' | 'B' | 'C'; every_days: number; last_counted: string; days_since: number | null; due: boolean; overdue_days: number; stock_value: string }
interface Abc { item_id: number; item_code: string; item_name: string; base_uom: string; class: 'A' | 'B' | 'C'; basis: string; annual_use_value: string; stock_qty: string; stock_value: string; cumulative_pct: string }
interface Rules { days_a: number; days_b: number; days_c: number; recount_value: string; recount_pct: string; recount_min_value: string }

const KEY = ['store', 'cycle'] as const
const TONE = { A: 'danger', B: 'warning', C: 'neutral' } as const
const pill = (on: boolean) => `whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] font-medium ${on ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground'}`

/** Count a little all the time: items ranked A, B, C by what they are worth, and the ones now due for counting. */
export default function CycleCounting() {
  const [view, setView] = useState<'due' | 'abc' | 'rules'>('due')
  const tabs = [['due', 'Due for counting'], ['abc', 'ABC ranking'], ['rules', 'Counting rules']] as const
  return (
    <div>
      <div className="mb-4 flex w-fit gap-1 rounded-xl bg-muted p-1" role="tablist">
        {tabs.map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={view === k} className={pill(view === k)} onClick={() => setView(k)}>{l}</button>)}
      </div>
      {view === 'due' ? <DueList /> : view === 'abc' ? <AbcList /> : <RulesForm />}
    </div>
  )
}

function DueList() {
  const nav = useNavigate()
  const { can } = useSession()
  const [storeId, setStoreId] = useState(0)
  const [pick, setPick] = useState<Record<number, boolean>>({})
  const rows = useQuery({ queryKey: [...KEY, 'due', storeId], queryFn: () => get<{ items: Due[] }>(`/api/store/cycle/due${storeId ? `?store_id=${storeId}` : ''}`) })
  const chosen = (rows.data?.items ?? []).filter((r) => pick[r.item_id])
  const create = useAction(() => post<{ id: number }>('/api/store/control/count', { store_id: storeId, count_date: new Date().toLocaleDateString('en-CA'), count_type: 'PARTIAL', item_ids: chosen.map((r) => r.item_id) }), {
    invalidate: [['store', 'control']], success: 'Count created', onSuccess: (c) => nav(`/store/hub/control/count/${c.id}`),
  })
  const columns: TableColumn<Due>[] = [
    ...(can(storePerm('control', 'create')) && storeId ? ([{ id: 'sel', header: '', width: '2.5rem', cell: (r) => <input type="checkbox" aria-label={`Count ${r.item_name}`} checked={!!pick[r.item_id]} onChange={(e) => setPick((p) => ({ ...p, [r.item_id]: e.target.checked }))} /> }] as TableColumn<Due>[]) : []),
    { id: 'item', header: 'Item', cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'store', header: 'Store', width: '5rem', cell: (r) => <span className="font-mono text-[13px]">{r.store_code}</span> },
    { id: 'cls', header: 'Class', width: '5rem', cell: (r) => <Badge tone={TONE[r.class]}>{r.class}</Badge> },
    { id: 'last', header: 'Last counted', width: '11rem', cell: (r) => (r.last_counted ? `${dmy(r.last_counted)} (${r.days_since}d ago)` : <span className="text-danger">Never</span>) },
    { id: 'every', header: 'Every', align: 'right', width: '6rem', hideBelow: 'md', cell: (r) => `${r.every_days} days` },
    { id: 'val', header: 'Stock value', align: 'right', width: '8rem', hideBelow: 'sm', cell: (r) => money(r.stock_value) },
  ]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Store" htmlFor="cc-store" className="w-56" hint={storeId ? undefined : 'Choose a store to pick items for a count.'}><StorePicker id="cc-store" value={storeId || null} placeholder="All my stores" onChange={(id) => { setStoreId(id ?? 0); setPick({}) }} /></Field>
        {storeId > 0 && can(storePerm('control', 'create')) && <Button className="ml-auto" loading={create.isPending} disabled={!chosen.length} onClick={() => create.mutate()}>Start a count of {chosen.length || 'the chosen'} item{chosen.length === 1 ? '' : 's'}</Button>}
      </div>
      {rows.isError ? <p role="alert" className="text-sm text-danger">Could not load what is due.</p> : (
        <DataTable label="Due for counting" rows={rows.data?.items ?? []} loading={rows.isPending} columns={columns} rowKey={(r) => `${r.store_id}-${r.item_id}`} empty="Nothing is due for counting." />
      )}
    </div>
  )
}

function AbcList() {
  const rows = useQuery({ queryKey: [...KEY, 'abc'], queryFn: () => get<{ items: Abc[] }>('/api/store/cycle/abc') })
  const columns: TableColumn<Abc>[] = [
    { id: 'item', header: 'Item', cell: (r) => <div><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></div> },
    { id: 'cls', header: 'Class', width: '5rem', sort: (r) => r.class, cell: (r) => <Badge tone={TONE[r.class]}>{r.class}</Badge> },
    { id: 'use', header: 'Used in the last year', align: 'right', width: '11rem', sort: (r) => Number(r.annual_use_value), cell: (r) => money(r.annual_use_value) },
    { id: 'qty', header: 'In stock', align: 'right', width: '9rem', hideBelow: 'md', cell: (r) => `${num(r.stock_qty)} ${r.base_uom}` },
    { id: 'val', header: 'Stock value', align: 'right', width: '8rem', hideBelow: 'sm', cell: (r) => money(r.stock_value) },
    { id: 'cum', header: 'Cumulative', align: 'right', width: '7rem', hideBelow: 'lg', cell: (r) => `${r.cumulative_pct}%` },
  ]
  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">Ranked by what each item was used for in the last year. A is the top 80% of that value, B the next 15%, C the rest. When nothing has been used yet, stock value is used instead.</p>
      {rows.isError ? <p role="alert" className="text-sm text-danger">Could not load the ranking.</p> : <DataTable label="ABC ranking" rows={rows.data?.items ?? []} loading={rows.isPending} columns={columns} rowKey={(r) => r.item_id} empty="No stock to rank yet." />}
    </div>
  )
}

function RulesForm() {
  const { can } = useSession()
  const canEdit = can(storePerm('control', 'create'))
  const rules = useQuery({ queryKey: [...KEY, 'rules'], queryFn: () => get<Rules>('/api/store/cycle/settings') })
  const [f, setF] = useState<Partial<Record<keyof Rules, string>>>({})
  const val = (k: keyof Rules) => f[k] ?? String(rules.data?.[k] ?? '')
  const save = useAction(() => put<Rules>('/api/store/cycle/settings', f), { invalidate: [[...KEY]], success: 'Rules saved', onSuccess: () => setF({}) })
  const field = (k: keyof Rules, label: string, hint: string) => <Field label={label} htmlFor={`cr-${k}`} hint={hint}><Input id={`cr-${k}`} inputMode="decimal" disabled={!canEdit || rules.isPending} value={val(k)} onChange={(e) => setF((x) => ({ ...x, [k]: e.target.value }))} /></Field>
  return (
    <form className="grid max-w-2xl gap-4 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
      {field('days_a', 'Count class A every (days)', 'The items worth most.')}
      {field('days_b', 'Count class B every (days)', '')}
      {field('days_c', 'Count class C every (days)', 'The items worth least.')}
      {field('recount_value', 'Count again if worth at least', 'A difference this large is counted a second time, blind. 0 = never on value.')}
      {field('recount_pct', 'Count again if this % of the books', 'Applies once the difference is worth the smallest amount below. 0 = never on percent.')}
      {field('recount_min_value', 'Smallest amount for the % rule', '')}
      {canEdit && <div className="sm:col-span-3"><Button type="submit" loading={save.isPending} disabled={!Object.keys(f).length}>Save rules</Button></div>}
    </form>
  )
}

/** The blind second count: the items to count again, with nothing about the books or the first count. */
export function RecountPanel({ countId }: { countId: number }) {
  const list = useQuery({ queryKey: [...KEY, 'recount', countId], queryFn: () => get<{ items: { item_id: number; item_code: string; item_name: string; base_uom: string }[] }>(`/api/store/cycle/recount/${countId}`) })
  const [qty, setQty] = useState<Record<number, string>>({})
  const save = useAction(() => post<{ still_to_recount: number }>(`/api/store/cycle/recount/${countId}`, { rows: Object.entries(qty).filter(([, v]) => v !== '').map(([id, v]) => ({ item_id: Number(id), qty: v })) }),
    { invalidate: [[...KEY], ['store', 'control']], success: 'Second count saved', onSuccess: () => setQty({}) })
  const items = list.data?.items ?? []
  if (!items.length) return null
  return (
    <section className="mt-6 rounded-lg border border-warning p-3" aria-labelledby="rc-h">
      <h3 id="rc-h" className="text-sm font-semibold">Count these again</h3>
      <p className="mb-3 text-xs text-muted-foreground">The first count was far from the books. Have someone count them again without seeing either; the second count is the one that stands.</p>
      <ul className="grid gap-2">
        {items.map((i) => (
          <li key={i.item_id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span><span className="font-medium">{i.item_name}</span> <span className="font-mono text-xs text-muted-foreground">{i.item_code}</span></span>
            <Input aria-label={`Second count of ${i.item_name}`} inputMode="decimal" className="w-40 text-right" placeholder={`0 ${i.base_uom}`} value={qty[i.item_id] ?? ''} onChange={(e) => setQty((q) => ({ ...q, [i.item_id]: e.target.value }))} />
          </li>
        ))}
      </ul>
      <div className="mt-3 flex justify-end"><Button loading={save.isPending} disabled={!Object.values(qty).some((v) => v !== '')} onClick={() => save.mutate()}>Save second count</Button></div>
    </section>
  )
}
