import { useState } from 'react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { drawFromOrder, schKeys, useWorkOrdersOf } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'

/** Draw a programme from a placed work order: each line becomes an activity whose progress comes from the measurement book. */
export function DrawModal({ job, open, onClose }: { job: number; open: boolean; onClose: () => void }) {
  const orders = useWorkOrdersOf(job)
  const [wo, setWo] = useState('')
  const [start, setStart] = useState(today())
  const [finish, setFinish] = useState(() => { const d = new Date(); d.setDate(d.getDate() + 90); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` })
  const list = orders.data ?? []
  const pick = wo || (list[0] ? String(list[0].id) : '')
  const draw = useAction(() => drawFromOrder(job, Number(pick), start, finish), { invalidate: [schKeys.all], success: (r) => r.message || 'Programme drawn', onSuccess: onClose })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Draw from a work order" description="Each line becomes an activity whose progress comes from the measurement book.">
      {list.length === 0 && !orders.isPending ? <p className="text-sm">This project has no placed work order to draw from.</p> : (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Work order" htmlFor="dw-wo" className="sm:col-span-2"><Select id="dw-wo" value={pick} onChange={(e) => setWo(e.target.value)} options={list.map((w) => ({ value: w.id, label: w.number }))} /></Field>
          <Field label="The work starts on" htmlFor="dw-start"><Input id="dw-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="And finishes by" htmlFor="dw-finish"><Input id="dw-finish" type="date" value={finish} onChange={(e) => setFinish(e.target.value)} /></Field>
        </div>
      )}
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {draw.error && <p role="alert" className="mr-auto text-[13px] text-danger">{draw.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={draw.isPending} disabled={!pick || !start || !finish} onClick={() => draw.mutate()}>Draw the programme</Button>
      </div>
    </Modal>
  )
}
