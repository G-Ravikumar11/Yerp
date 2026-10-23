import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Button, Field, Input } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useAction } from '@/lib/mutate'
import { storePut, type StoreItemOption } from '@/api/store'
import { ItemPicker } from '../shared'
import { RecountPanel } from './CycleCounting'
import { controlKeys, money, num, type Doc, type DocLine } from './api'

/**
 * A count's lines. While it is open the counter types what is on the shelf against each item (in the item's base unit), and a reason where
 * it differs from the books. Without the right to see the system quantity (a blind count) the books are not shown until the count is submitted.
 */
export default function CountSheet({ doc, editable }: { doc: Doc; editable: boolean }) {
  const lines = doc.lines ?? []
  const reveal = !!doc.revealed
  const [counted, setCounted] = useState<Record<number, string>>({})
  const [why, setWhy] = useState<Record<number, string>>({})
  const [extra, setExtra] = useState<{ item: StoreItemOption | null; qty: string; rate: string; reason: string }>({ item: null, qty: '', rate: '', reason: '' })
  const valueOf = (l: DocLine) => counted[l.id] ?? (l.counted_qty != null ? String(Number(l.counted_qty)) : '')
  const reasonOf = (l: DocLine) => why[l.id] ?? l.reason ?? ''
  const changed = lines.filter((l) => counted[l.id] !== undefined || why[l.id] !== undefined)
  const save = useAction(
    (rows: { item_id: number; counted_qty: string; uom: string; reason: string; rate?: string }[]) => storePut<Doc>('control', `/count/${doc.id}/sheet`, { rows }),
    { invalidate: [[...controlKeys.all]], success: 'Counts saved', onSuccess: () => { setCounted({}); setWhy({}); setExtra({ item: null, qty: '', rate: '', reason: '' }) } },
  )
  const columns: TableColumn<DocLine>[] = [
    { id: 'item', header: 'Item', cell: (l) => <div><div className="font-medium">{l.item_name} {!l.in_snapshot && <span className="text-xs text-warning">(not in the books)</span>}</div><div className="font-mono text-xs text-muted-foreground">{l.item_code}</div></div> },
    ...(reveal ? ([{ id: 'sys', header: 'Books', align: 'right', width: '8rem', cell: (l) => (l.system_qty != null ? `${num(l.system_qty)} ${l.base_uom}` : '') }] as TableColumn<DocLine>[]) : []),
    {
      id: 'cnt',
      header: 'Counted',
      align: 'right',
      width: '10rem',
      cell: (l) => (editable
        ? <Input aria-label={`Counted quantity of ${l.item_name}`} inputMode="decimal" className="text-right" placeholder={`0 ${l.base_uom}`} value={valueOf(l)} onChange={(e) => setCounted((c) => ({ ...c, [l.id]: e.target.value }))} />
        : l.counted_qty != null ? `${num(l.counted_qty)} ${l.base_uom}` : <span className="text-muted-foreground">Not counted</span>),
    },
    ...(reveal ? ([
      { id: 'var', header: 'Difference', align: 'right', width: '8rem', cell: (l) => (l.variance_qty != null && Number(l.variance_qty) !== 0 ? <span className={Number(l.variance_qty) < 0 ? 'text-danger' : 'text-success'}>{Number(l.variance_qty) > 0 ? '+' : ''}{num(l.variance_qty)}</span> : l.counted_qty != null ? '-' : '') },
      { id: 'val', header: 'Value', align: 'right', width: '8rem', hideBelow: 'sm', cell: (l) => (l.variance_value != null && Number(l.variance_value) !== 0 ? money(l.variance_value) : '') },
      ...(lines.some((l) => Number(l.arrived_since) > 0) ? [{ id: 'arr', header: 'Came in since', align: 'right', width: '8rem', hideBelow: 'sm', cell: (l: DocLine) => (Number(l.arrived_since) > 0 ? <span title="Received while the count was on - kept apart, not counted">+{num(l.arrived_since ?? '')}</span> : '') }] : []),
    ] as TableColumn<DocLine>[]) : []),
    { id: 'why', header: 'Reason for a difference', width: '14rem', hideBelow: 'md', cell: (l) => (editable ? <Input aria-label={`Reason for ${l.item_name}`} value={reasonOf(l)} onChange={(e) => setWhy((w) => ({ ...w, [l.id]: e.target.value }))} /> : l.reason || '') },
  ]
  return (
    <div>
      {doc.status === 'DRAFT' && !doc.started && <p className="mb-3 text-sm text-muted-foreground">Start the count to freeze the store and list what the books say is there. Nothing is counted until then.</p>}
      {doc.started && !reveal && <p role="status" className="mb-3 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">This is a blind count: the books are hidden while you count, so count what is really there.</p>}
      <DataTable label="Count sheet" rows={lines} columns={columns} rowKey={(l) => l.id} empty={doc.started ? 'Nothing to count.' : 'The lines appear once the count is started.'} />
      {editable && doc.started && <RecountPanel countId={doc.id} />}
      {editable && (
        <>
          <div className="mt-3 flex justify-end">
            <Button loading={save.isPending} disabled={!changed.length} onClick={() => save.mutate(changed.filter((l) => valueOf(l) !== '').map((l) => ({ item_id: l.item_id, counted_qty: valueOf(l), uom: l.base_uom, reason: reasonOf(l) })))}>Save counts</Button>
          </div>
          {doc.count_type === 'FULL' && (
            <section className="mt-6" aria-labelledby="cs-extra">
              <h3 id="cs-extra" className="mb-2 border-b pb-1 text-sm font-semibold">Found something the books do not have?</h3>
              <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (extra.item && extra.qty) save.mutate([{ item_id: extra.item.id, counted_qty: extra.qty, uom: extra.item.base_uom, reason: extra.reason, rate: extra.rate }]) }}>
                <Field label="Item" htmlFor="cs-item" className="min-w-56 flex-1"><ItemPicker id="cs-item" value={extra.item} onChange={(item) => setExtra({ ...extra, item })} /></Field>
                <Field label={`Quantity${extra.item ? ` (${extra.item.base_uom})` : ''}`} htmlFor="cs-qty" className="w-32"><Input id="cs-qty" inputMode="decimal" className="text-right" value={extra.qty} onChange={(e) => setExtra({ ...extra, qty: e.target.value })} /></Field>
                <Field label="Rate worth" htmlFor="cs-rate" className="w-32"><Input id="cs-rate" inputMode="decimal" className="text-right" value={extra.rate} onChange={(e) => setExtra({ ...extra, rate: e.target.value })} /></Field>
                <Field label="Where found" htmlFor="cs-why" className="min-w-40 flex-1"><Input id="cs-why" value={extra.reason} onChange={(e) => setExtra({ ...extra, reason: e.target.value })} /></Field>
                <Button type="submit" variant="outline" loading={save.isPending} disabled={!extra.item || !extra.qty || !extra.rate}><Plus /> Add</Button>
              </form>
            </section>
          )}
        </>
      )}
    </div>
  )
}
