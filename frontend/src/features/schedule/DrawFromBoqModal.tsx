import { useState } from 'react'
import { Button, Field, Input, Modal } from '@/components/ui'
import { drawFromBoq, schKeys } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'

/** Draw the programme from the project's BOQ: by section, with its lines as tasks, or one activity per priced line. */
export function DrawFromBoqModal({ job, open, onClose }: { job: number; open: boolean; onClose: () => void }) {
  const [by, setBy] = useState<'section' | 'item'>('section')
  const [start, setStart] = useState(today())
  const [finish, setFinish] = useState(() => { const d = new Date(); d.setDate(d.getDate() + 90); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` })
  const draw = useAction(() => drawFromBoq(job, start, finish, by), { invalidate: [schKeys.all], success: (r) => r.message || 'Programme drawn', onSuccess: onClose })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Draw from the BOQ" description="What the client's sheet lists, spread across the span given and weighted by what each is worth.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Draw" htmlFor="db-by" className="sm:col-span-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm ${by === 'section' ? 'border-primary bg-primary-soft' : 'border-border'}`}>
              <input type="radio" name="db-by" id="db-by" checked={by === 'section'} onChange={() => setBy('section')} className="mt-0.5" />
              <span><strong>By section</strong><br /><span className="text-xs text-muted-foreground">One activity per section, its lines as tasks to tick off.</span></span>
            </label>
            <label className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm ${by === 'item' ? 'border-primary bg-primary-soft' : 'border-border'}`}>
              <input type="radio" name="db-by" checked={by === 'item'} onChange={() => setBy('item')} className="mt-0.5" />
              <span><strong>By item</strong><br /><span className="text-xs text-muted-foreground">One activity per priced line; a line on a client work order takes its progress from the measurement book.</span></span>
            </label>
          </div>
        </Field>
        <Field label="The work starts on" htmlFor="db-start"><Input id="db-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="And finishes by" htmlFor="db-finish"><Input id="db-finish" type="date" value={finish} onChange={(e) => setFinish(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {draw.error && <p role="alert" className="mr-auto text-[13px] text-danger">{draw.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={draw.isPending} disabled={!start || !finish} onClick={() => draw.mutate()}>Draw the programme</Button>
      </div>
    </Modal>
  )
}
