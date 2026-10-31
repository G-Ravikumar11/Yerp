import { useMemo, useState } from 'react'
import { Lock } from 'lucide-react'
import { DataGrid, type Column } from '@/components/grid'
import { Button, Field, Input, Modal, Select, Tabs, Textarea } from '@/components/ui'
import { editRfq, openRfq, openRfqFromOrder, rfqKeys, type Statement } from '@/api/rfq'
import { useItems, useItemVocabulary } from '@/api/items'
import { usePlacedOrders } from '@/api/stock'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { formatQty, today } from '@/lib/format'

interface Row { item_code: string; description: string; uom: string; qty: number | null }
const blank = (): Row => ({ item_code: '', description: '', uom: '', qty: null })

/**
 * A new enquiry, or an open one put right. The items come from the item master (or are typed, for something not in
 * it); a work order's budget can fill them instead. Once a supplier has quoted, the items stay as they were priced.
 */
export function EnquiryFormModal({ open, statement, onClose, onSaved }: { open: boolean; statement?: Statement | null; onClose: () => void; onSaved: (id: number) => void }) {
  const editing = !!statement
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="xl" title={editing ? `Edit ${statement!.rfq.number}` : 'New enquiry'}
      description={editing ? 'Change what the enquiry says. Suppliers who open their link see the change.' : 'What you need, how much, and by when. Suppliers are asked once it is open.'}>
      {open && <Form key={statement?.rfq.id ?? 'new'} statement={statement ?? null} onClose={onClose} onSaved={onSaved} />}
    </Modal>
  )
}

function Form({ statement, onClose, onSaved }: { statement: Statement | null; onClose: () => void; onSaved: (id: number) => void }) {
  const jobs = useProjects()
  const orders = usePlacedOrders()
  const rm = useItems('RM', '')
  const vocab = useItemVocabulary()
  const r = statement?.rfq
  const locked = !!statement && statement.suppliers.length > 0
  const [from, setFrom] = useState<'list' | 'order'>('list')
  const [wo, setWo] = useState('')
  const [title, setTitle] = useState(r?.title ?? '')
  const [job, setJob] = useState(r?.job_id ? String(r.job_id) : '')
  const [needed, setNeeded] = useState(r?.needed_by ?? '')
  const [due, setDue] = useState(r?.quotes_due ?? '')
  const [notes, setNotes] = useState(r?.notes ?? '')
  const [rows, setRows] = useState<Row[]>(() => (statement?.lines ?? []).map((l) => ({ item_code: l.item_code, description: l.description, uom: l.uom, qty: l.qty })))
  const master = useMemo(() => new Map((rm.data?.items ?? []).map((i) => [i.item_code, i])), [rm.data])

  const columns = useMemo<Column<Row>[]>(() => [
    {
      id: 'item_code', header: 'Item', hint: 'From the item master', type: 'select', width: 260, pin: true,
      options: (rm.data?.items ?? []).map((i) => ({ value: i.item_code, label: `${i.item_code} - ${i.item_name}` })),
      // Choosing an item brings its name and unit, unless they were already typed.
      set: (row, v) => {
        const it = master.get(String(v ?? ''))
        return { ...row, item_code: String(v ?? ''), description: row.description || it?.item_name || '', uom: row.uom || it?.units_of_measure || '' }
      },
    },
    { id: 'description', header: 'Description', hint: 'What the supplier reads', width: 420, placeholder: 'Or type something not in the master' },
    { id: 'uom', header: 'Unit', type: 'select', width: 100, freeText: true, options: vocab.data?.units ?? [] },
    { id: 'qty', header: 'Quantity', type: 'number', width: 110, align: 'right' },
  ], [rm.data, master, vocab.data])

  // The items as they are on screen, counting a quantity still being typed into a cell.
  const [draft, setDraft] = useState<Row[] | null>(null)
  const live = draft ?? rows
  const lines = live.filter((x) => (x.qty ?? 0) > 0 && (x.description.trim() || x.item_code))
  const half = live.filter((x) => (x.description.trim() || x.item_code) && !((x.qty ?? 0) > 0)).length
  const body = () => ({ title: title.trim(), job_id: job ? Number(job) : null, needed_by: needed, notes: notes.trim(), quotes_due: due,
    lines: lines.map((x) => ({ item_code: x.item_code, description: (x.description || master.get(x.item_code)?.item_name || x.item_code).trim(), uom: x.uom, qty: x.qty ?? 0 })) })
  const save = useAction(
    () => (statement ? editRfq(statement.rfq.id, body()).then((x) => ({ ...x, id: statement.rfq.id }))
      : (from === 'order' ? openRfqFromOrder(Number(wo)) : openRfq(body())).then((x) => ({ ...x, id: x.rfq.id }))),
    { invalidate: [rfqKeys.all], onSuccess: (x) => onSaved(x.id) },
  )
  const fromOrder = !statement && from === 'order'
  // Why the button is greyed out, in words: the first box still to fill.
  const missing = (() => {
    if (fromOrder) return wo ? null : 'choose the work order'
    if (!title.trim()) return 'fill in What is it for'
    if (lines.length) return null
    const started = live.map((x, i) => ({ x, n: i + 1 })).filter(({ x }) => x.item_code || x.description.trim() || x.qty)
    if (!started.length) return 'add an item - choose one from the master or type a Description'
    for (const { x, n } of started) {
      if (!x.item_code && !x.description.trim()) return `line ${n} needs an Item or a Description`
      if (!((x.qty ?? 0) > 0)) return `line ${n} needs a Quantity`
    }
    return 'add an item with a quantity'
  })()
  const ready = !missing

  return (
    <div className="grid gap-5">
      {!statement && (
        <Tabs label="How to list the items" value={from} onChange={setFrom} items={[{ value: 'list', label: 'List the items' }, { value: 'order', label: "From a work order's budget" }]} />
      )}
      {fromOrder ? (
        <div className="grid gap-2">
          <Field label="Work order" htmlFor="rn-wo" hint="The enquiry asks for what its budget still needs: less what is in the store and already on order.">
            <Select id="rn-wo" value={wo} placeholder="Choose the work order" onChange={(e) => setWo(e.target.value)} options={(orders.data ?? []).map((w) => ({ value: w.id, label: `${w.number} - ${w.job_name}` }))} />
          </Field>
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-5">
            <Field label="What is it for" htmlFor="rn-title" className="sm:col-span-2"><Input id="rn-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Cement and steel for the Block A raft" autoFocus /></Field>
            <Field label="Project" htmlFor="rn-job"><Select id="rn-job" value={job} placeholder="No particular project" onChange={(e) => setJob(e.target.value)} options={(jobs.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
            <Field label="Needed by" htmlFor="rn-needed"><Input id="rn-needed" type="date" value={needed} onChange={(e) => setNeeded(e.target.value)} /></Field>
            <Field label="Quotes due by" htmlFor="rn-due" hint="Optional. Suppliers who have not quoted are reminded, and you get the L1 summary on the day."><Input id="rn-due" type="date" min={today()} value={due} onChange={(e) => setDue(e.target.value)} /></Field>
          </div>
          <div>
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <p className="text-sm font-medium">Items</p>
              <p className="text-xs text-muted-foreground">{locked ? '' : 'Pick from the item master or type. Paste rows straight from Excel.'}</p>
            </div>
            {locked ? (
              <div className="overflow-hidden rounded-lg border border-border">
                <p className="flex items-center gap-2 border-b border-border bg-surface px-3 py-2 text-[13px] text-muted-foreground"><Lock className="size-3.5" /> Suppliers have already priced these items, so they stay as they are. Cancel the enquiry and open a new one if what is needed has changed.</p>
                <ul className="divide-y divide-border text-sm">
                  {statement!.lines.map((l) => (
                    <li key={l.rfq_line_id} className="flex items-baseline justify-between gap-4 px-3 py-2">
                      <span className="min-w-0 truncate">{l.description}{l.item_code && <span className="ml-2 font-mono text-xs text-muted-foreground">{l.item_code}</span>}</span>
                      <span className="shrink-0 tabular text-muted-foreground">{formatQty(l.qty)} {l.uom}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <DataGrid aria-label="Enquiry items" columns={columns} rows={rows} onRowsChange={setRows} onDraft={setDraft} newRow={blank} minRows={4} maxHeight={300} />
            )}
          </div>
          <Field label="Notes for suppliers" htmlFor="rn-notes" hint="Optional: delivery address, brand wanted, unloading. Suppliers see this on their link.">
            <Textarea id="rn-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
        </>
      )}
      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error ? <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>
          : missing ? <p className="mr-auto text-[13px] text-muted-foreground">To {statement ? 'save' : 'open it'}, {missing}.</p>
          : !fromOrder && !locked && <p className="mr-auto text-xs text-muted-foreground">{lines.length} {lines.length === 1 ? 'item' : 'items'}{half ? ` · ${half} without a quantity, left out` : ''}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!ready} onClick={() => save.mutate()}>{statement ? 'Save changes' : 'Open the enquiry'}</Button>
      </div>
    </div>
  )
}
