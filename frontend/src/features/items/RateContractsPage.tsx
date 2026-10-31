import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Field, Input, Modal, Select } from '@/components/ui'
import { useItems } from '@/api/items'
import { useSuppliers } from '@/api/ledger'
import { makeContract, priceKeys, removeRateContract, useContracts, type Contract } from '@/api/poControls'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const tone = (c: Contract) => (c.status === 'expired' ? 'neutral' : c.days_left != null && c.days_left <= 30 ? 'warning' : c.status === 'in force' ? 'success' : 'info') as 'neutral' | 'warning' | 'success' | 'info'

/** Store > Rate Contracts: a supplier's agreed rates for chosen items, usually for a year. An order to that supplier picks
 * the rates by itself; purchasing is told 30 and 7 days before a contract ends. */
export default function RateContractsPage() {
  const q = useContracts()
  const [creating, setCreating] = useState(false)
  const drop = useAction((id: number) => removeRateContract(id), { invalidate: [priceKeys.all] })
  const list = q.data ?? []
  return (
    <>
      <PageHeader eyebrow="Store" title="Rate Contracts" description="Yearly rates agreed with a supplier for chosen items. A purchase order to that supplier picks these rates by itself, and one priced above them is flagged. You are told 30 and 7 days before a contract ends."
        actions={<Button onClick={() => setCreating(true)}><Plus /> New contract</Button>} />
      {q.isPending ? <p className="text-sm text-muted-foreground">Loading...</p> : list.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border py-10 text-center text-sm text-muted-foreground">No rate contracts yet. Press New contract to agree a supplier's rates for the year.</p>
      ) : (
        <ul className="grid gap-3 lg:grid-cols-2">
          {list.map((c) => (
            <li key={c.contract_no} className="rounded-xl border border-border bg-card p-4 shadow-card">
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <div><span className="font-mono text-sm">{c.contract_no}</span> <strong className="ml-1">{c.supplier_name}</strong>{c.reference && <span className="ml-2 text-xs text-muted-foreground">{c.reference}</span>}</div>
                <Badge tone={tone(c)} dot>{c.status === 'in force' && c.days_left != null && c.days_left <= 30 ? `ends in ${c.days_left} days` : c.status}</Badge>
              </div>
              <p className="mb-2 text-xs text-muted-foreground">{formatDate(c.valid_from)} to {formatDate(c.valid_to)}</p>
              <ul className="divide-y divide-border text-sm">
                {c.items.map((i) => (
                  <li key={i.id} className="flex items-center gap-2 py-1.5">
                    <span className="font-mono text-xs text-muted-foreground">{i.item_code}</span><span className="min-w-0 flex-1 truncate">{i.item_name}</span>
                    <strong className="tabular">{formatINR(i.rate)}</strong>
                    <button type="button" aria-label={`Take ${i.item_code} off ${c.contract_no}`} className="text-muted-foreground hover:text-danger" onClick={() => drop.mutate(i.id)}><Trash2 className="size-4" /></button>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {creating && <NewContract onClose={() => setCreating(false)} />}
    </>
  )
}

function NewContract({ onClose }: { onClose: () => void }) {
  const items = useItems('RM', '')
  const suppliers = useSuppliers()
  const [f, setF] = useState({ supplier_name: '', valid_from: today(), valid_to: '', reference: '' })
  const [lines, setLines] = useState<{ item_code: string; rate: string }[]>([{ item_code: '', rate: '' }])
  const chosen = lines.filter((l) => l.item_code && Number(l.rate) > 0)
  const save = useAction(() => makeContract({ ...f, supplier_name: f.supplier_name.trim(), items: chosen.map((l) => ({ item_code: l.item_code, rate: Number(l.rate) })) }),
    { invalidate: [priceKeys.all], success: (r) => r.message, onSuccess: onClose })
  const names = [...(suppliers.data?.suppliers ?? []).map((s) => s.name), ...(suppliers.data?.unregistered ?? [])]
  const set = (i: number, patch: Partial<{ item_code: string; rate: string }>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title="New rate contract" description="The supplier's agreed rates for the items chosen. A year from the start unless you say when it ends.">
      <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); if (f.supplier_name.trim() && chosen.length) save.mutate() }}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Supplier" htmlFor="nc-sup"><Input id="nc-sup" list="nc-sups" autoComplete="off" value={f.supplier_name} onChange={(e) => setF({ ...f, supplier_name: e.target.value })} /><datalist id="nc-sups">{names.map((n) => <option key={n} value={n} />)}</datalist></Field>
          <Field label="Reference" htmlFor="nc-ref"><Input id="nc-ref" value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} placeholder="Their letter or our agreement number" /></Field>
          <Field label="From" htmlFor="nc-from"><Input id="nc-from" type="date" value={f.valid_from} onChange={(e) => setF({ ...f, valid_from: e.target.value })} /></Field>
          <Field label="To" htmlFor="nc-to" hint="Leave empty for a year."><Input id="nc-to" type="date" min={f.valid_from} value={f.valid_to} onChange={(e) => setF({ ...f, valid_to: e.target.value })} /></Field>
        </div>
        <div className="grid gap-2">
          <p className="text-sm font-medium">Items and agreed rates</p>
          {lines.map((l, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <Select aria-label={`Item ${i + 1}`} className="min-w-64 flex-1" value={l.item_code} placeholder="Choose an item" onChange={(e) => set(i, { item_code: e.target.value })}
                options={(items.data?.items ?? []).map((it) => ({ value: it.item_code, label: `${it.item_code} - ${it.item_name}` }))} />
              <Input aria-label={`Rate for item ${i + 1}`} inputMode="decimal" className="w-32 text-right" placeholder="Rate" value={l.rate} onChange={(e) => set(i, { rate: e.target.value })} />
              {lines.length > 1 && <Button type="button" size="icon-sm" variant="ghost" aria-label={`Remove item ${i + 1}`} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}><Trash2 /></Button>}
            </div>
          ))}
          <Button type="button" size="sm" variant="outline" className="justify-self-start" onClick={() => setLines((ls) => [...ls, { item_code: '', rate: '' }])}><Plus /> Another item</Button>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
          {save.error ? <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p> : (!f.supplier_name.trim() || !chosen.length) && <p className="mr-auto text-[13px] text-muted-foreground">To keep it, {!f.supplier_name.trim() ? 'name the supplier' : 'add an item with its rate'}.</p>}
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!f.supplier_name.trim() || !chosen.length}>Keep the contract</Button>
        </div>
      </form>
    </Modal>
  )
}
