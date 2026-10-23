import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Field, Input } from '@/components/ui'
import { get, post, put, del } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { ItemPicker } from '../shared'
import type { StoreItemOption } from '@/api/store'

interface Level { item_id: number; item_code: string; item_name: string; base_uom: string; reorder_level: string | null; min_qty: string | null; max_qty: string | null; default_reorder_level: string; default_min_qty: string; default_max_qty: string }

const n = (v: string | null, fallback: string) => (v === null ? <span className="text-muted-foreground">{Number(fallback)} (item)</span> : Number(v))

/** Reorder, minimum and maximum quantity for this store, where they differ from the item's own; and a check for stock already low. */
export default function StoreLevels({ storeId, canEdit }: { storeId: number; canEdit: boolean }) {
  const key = ['store', 'levels', storeId] as const
  const rows = useQuery({ queryKey: key, queryFn: () => get<{ items: Level[] }>(`/api/store/levels/${storeId}`) })
  const [item, setItem] = useState<StoreItemOption | null>(null)
  const [f, setF] = useState({ reorder_level: '', min_qty: '', max_qty: '' })
  const refresh = [[...key], ['store', 'enquiry'], ['store', 'reports']]
  const save = useAction(() => put<Level>(`/api/store/levels/${storeId}/${item?.id}`, f), { invalidate: refresh, success: 'Levels saved for this store', onSuccess: () => { setItem(null); setF({ reorder_level: '', min_qty: '', max_qty: '' }) } })
  const drop = useAction((id: number) => del<{ message: string }>(`/api/store/levels/${storeId}/${id}`), { invalidate: refresh })
  const scan = useAction(() => post<{ raised: number }>('/api/store/levels/scan'), { success: (r) => (r.raised ? `${r.raised} reorder alert${r.raised === 1 ? '' : 's'} raised` : 'Nothing new is low') })
  return (
    <section aria-labelledby="sd-levels">
      <div className="mb-2 flex flex-wrap items-center gap-2 border-b pb-1">
        <h3 id="sd-levels" className="mr-auto text-sm font-semibold">Stock levels for this store</h3>
        {canEdit && <Button size="sm" variant="ghost" loading={scan.isPending} onClick={() => scan.mutate()}>Check for low stock now</Button>}
      </div>
      <p className="mb-2 text-xs text-muted-foreground">An item uses the levels in its settings unless this store has its own. Blank means the item's.</p>
      {rows.isPending ? <p className="text-sm text-muted-foreground">Loading...</p> : (rows.data?.items ?? []).length === 0 ? <p className="text-sm text-muted-foreground">No item has levels of its own here.</p> : (
        <ul className="divide-y rounded-lg border">
          {(rows.data?.items ?? []).map((l) => (
            <li key={l.item_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
              <span><span className="font-medium">{l.item_name}</span> <span className="font-mono text-xs text-muted-foreground">{l.item_code}</span></span>
              <span className="flex flex-wrap items-center gap-3">
                <span>Reorder {n(l.reorder_level, l.default_reorder_level)}</span><span>Min {n(l.min_qty, l.default_min_qty)}</span><span>Max {n(l.max_qty, l.default_max_qty)}</span> <span className="text-muted-foreground">{l.base_uom}</span>
                {canEdit && <Button size="sm" variant="ghost" aria-label={`Use the item's levels for ${l.item_name}`} onClick={() => drop.mutate(l.item_id)}>Remove</Button>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <form className="mt-2 grid gap-2 sm:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); if (item) save.mutate() }}>
          <Field label="Item" htmlFor="lv-item"><ItemPicker id="lv-item" value={item} onChange={setItem} /></Field>
          <Field label="Reorder at" htmlFor="lv-re"><Input id="lv-re" inputMode="decimal" value={f.reorder_level} onChange={(e) => setF({ ...f, reorder_level: e.target.value })} /></Field>
          <Field label="Minimum" htmlFor="lv-min"><Input id="lv-min" inputMode="decimal" value={f.min_qty} onChange={(e) => setF({ ...f, min_qty: e.target.value })} /></Field>
          <Field label="Maximum" htmlFor="lv-max"><Input id="lv-max" inputMode="decimal" value={f.max_qty} onChange={(e) => setF({ ...f, max_qty: e.target.value })} /></Field>
          <Button type="submit" variant="outline" loading={save.isPending} disabled={!item || (!f.reorder_level && !f.min_qty && !f.max_qty)}>Set</Button>
        </form>
      )}
    </section>
  )
}
