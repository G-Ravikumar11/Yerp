import { useState } from 'react'
import { Plus, X } from 'lucide-react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { openRfq, openRfqFromOrder, rfqKeys } from '@/api/rfq'
import { usePlacedOrders } from '@/api/stock'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'

const UNITS = ['cum', 'sqm', 'rmt', 'Nos', 'MT', 'Kgs', 'Bags', 'Litres', 'Lot']
const blank = () => ({ item_code: '', description: '', uom: 'Bags', qty: 0 })

/** Ask suppliers: list what is wanted, or build the enquiry from a work order's budget. */
export function NewRfqModal({ open, onClose, onOpened }: { open: boolean; onClose: () => void; onOpened: (id: number) => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="New enquiry" description="Ask three suppliers before an order goes out." size="lg">
      {open && <Form onClose={onClose} onOpened={onOpened} />}
    </Modal>
  )
}

function Form({ onClose, onOpened }: { onClose: () => void; onOpened: (id: number) => void }) {
  const jobs = useProjects()
  const orders = usePlacedOrders()
  const [wo, setWo] = useState('')
  const [title, setTitle] = useState('')
  const [job, setJob] = useState('')
  const [needed, setNeeded] = useState('')
  const [lines, setLines] = useState([blank()])
  const edit = (i: number, patch: Partial<ReturnType<typeof blank>>) => setLines((l) => l.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  const save = useAction(() => (wo ? openRfqFromOrder(Number(wo)) : openRfq({ title, job_id: job ? Number(job) : null, needed_by: needed, lines: lines.filter((l) => l.description.trim() || l.item_code.trim()) })), { invalidate: [rfqKeys.all], success: (r) => r.message, onSuccess: (r) => onOpened(r.rfq.id) })
  return (
    <div>
      <Field label="Build it from a work order's budget" htmlFor="rn-wo"><Select id="rn-wo" value={wo} placeholder="- or list the lines below -" onChange={(e) => setWo(e.target.value)} options={(orders.data ?? []).map((w) => ({ value: w.id, label: `${w.number} - ${w.job_name}` }))} /></Field>
      {!wo && (
        <>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <Field label="Title" htmlFor="rn-title" className="sm:col-span-3"><Input id="rn-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Cement for the raft" autoFocus /></Field>
            <Field label="Project" htmlFor="rn-job" className="sm:col-span-2"><Select id="rn-job" value={job} placeholder="No particular project" onChange={(e) => setJob(e.target.value)} options={(jobs.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
            <Field label="Needed by" htmlFor="rn-needed"><Input id="rn-needed" type="date" value={needed} onChange={(e) => setNeeded(e.target.value)} /></Field>
          </div>
          <div className="mt-4 grid gap-2">
            {lines.map((l, i) => (
              <div key={i} className="grid grid-cols-[1fr_2fr_90px_100px_32px] items-center gap-2">
                <Input aria-label={`Code ${i + 1}`} placeholder="code" value={l.item_code} onChange={(e) => edit(i, { item_code: e.target.value })} />
                <Input aria-label={`What ${i + 1}`} placeholder="What" value={l.description} onChange={(e) => edit(i, { description: e.target.value })} />
                <Select aria-label={`Unit ${i + 1}`} value={l.uom} onChange={(e) => edit(i, { uom: e.target.value })} options={UNITS.map((u) => ({ value: u, label: u }))} />
                <NumField aria-label={`Qty ${i + 1}`} placeholder="Qty" value={l.qty} onValue={(n) => edit(i, { qty: n })} />
                <button type="button" aria-label={`Remove line ${i + 1}`} onClick={() => setLines(lines.filter((_, j) => j !== i))}><X className="size-4" /></button>
              </div>
            ))}
          </div>
          <Button size="sm" variant="ghost" className="mt-1" onClick={() => setLines([...lines, blank()])}><Plus /> Line</Button>
        </>
      )}
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!wo && !title.trim()} onClick={() => save.mutate()}>Open the enquiry</Button>
      </div>
    </div>
  )
}
