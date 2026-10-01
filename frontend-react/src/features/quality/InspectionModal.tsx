import { useState } from 'react'
import { Image, FileText } from 'lucide-react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { closeInspection, qcKeys, saveInspection, startInspection, useChecklists, type Inspection } from '@/api/quality'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'

/** Start a checklist for a place. */
export function NewInspectionModal({ job, open, onClose, onStarted }: { job: number; open: boolean; onClose: () => void; onStarted: (i: Inspection) => void }) {
  const lists = useChecklists()
  const [list, setList] = useState('')
  const [where, setWhere] = useState('')
  const [witness, setWitness] = useState('')
  const names = Object.keys(lists.data ?? {})
  const start = useAction(() => startInspection({ job_id: job, checklist: list || names[0], location: where, witnessed_by: witness }), { invalidate: [qcKeys.all], success: false, onSuccess: (r) => onStarted(r.inspection) })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="New inspection" description="Walk the checklist before the work is covered up.">
      <div className="grid gap-4">
        <Field label="Checklist" htmlFor="qn-list"><Select id="qn-list" value={list || names[0] || ''} onChange={(e) => setList(e.target.value)} options={names.map((n) => ({ value: n, label: n }))} /></Field>
        <Field label="Where" htmlFor="qn-where"><Input id="qn-where" value={where} placeholder="Raft, grid A-C" onChange={(e) => setWhere(e.target.value)} /></Field>
        <Field label="Witnessed by" htmlFor="qn-witness"><Input id="qn-witness" value={witness} placeholder="Client's engineer" onChange={(e) => setWitness(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {start.error && <p role="alert" className="mr-auto text-[13px] text-danger">{start.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={start.isPending} disabled={!names.length} onClick={() => start.mutate()}>Start it</Button>
      </div>
    </Modal>
  )
}

/** Walk one inspection: ok, not ok or not applicable for each check, and close it as passed or failed. */
export function InspectionModal({ inspection, onClose, onPhotos, onNcr }: { inspection: Inspection | null; onClose: () => void; onPhotos: (i: Inspection) => void; onNcr: (i: Inspection) => void }) {
  return (
    <Modal open={!!inspection} onOpenChange={(o) => !o && onClose()} title={inspection ? `${inspection.number} - ${inspection.checklist}${inspection.location ? ` - ${inspection.location}` : ''}` : 'Inspection'} size="xl">
      {inspection && <Walk key={`${inspection.id}-${inspection.result}`} inspection={inspection} onClose={onClose} onPhotos={onPhotos} onNcr={onNcr} />}
    </Modal>
  )
}

function Walk({ inspection, onClose, onPhotos, onNcr }: { inspection: Inspection; onClose: () => void; onPhotos: (i: Inspection) => void; onNcr: (i: Inspection) => void }) {
  const { can } = useSession()
  const open = inspection.result === 'OPEN'
  const [items, setItems] = useState(() => inspection.items.map((x) => ({ ...x })))
  const edit = (n: number, patch: Partial<(typeof items)[number]>) => setItems((l) => l.map((x, i) => (i === n ? { ...x, ...patch } : x)))
  const save = useAction((close: boolean) => saveInspection({ ...inspection, items }).then(async (r) => (close ? closeInspection(inspection.id) : r)), {
    invalidate: [qcKeys.all],
    success: (r) => (r.inspection.result === 'OPEN' ? 'Saved' : `${r.inspection.number} ${r.inspection.result.toLowerCase()}`),
    onSuccess: (r) => { if (r.inspection.result !== 'OPEN') onClose() },
  })
  return (
    <div>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table aria-label="Checks" className="w-full text-[13.5px]">
          <thead className="bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Check</th><th className="px-2 py-2 text-center">OK</th><th className="px-2 py-2 text-center">Not OK</th><th className="px-2 py-2 text-center">N/A</th><th className="px-3 py-2">Remark</th></tr></thead>
          <tbody>
            {items.map((x, n) => (
              <tr key={n} className="border-t border-border">
                <td className="px-3 py-2">{x.item}</td>
                {(['ok', 'not ok', 'na'] as const).map((v) => <td key={v} className="px-2 py-2 text-center"><input type="radio" aria-label={`${x.item}: ${v}`} name={`qc-${n}`} checked={x.result === v} disabled={!open} onChange={() => edit(n, { result: v })} /></td>)}
                <td className="px-3 py-2"><Input aria-label={`Remark for ${x.item}`} value={x.remark ?? ''} disabled={!open} onChange={(e) => edit(n, { remark: e.target.value })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[13px] text-muted-foreground">By {inspection.inspected_by} on {inspection.inspected_on}{inspection.witnessed_by && `, witnessed by ${inspection.witnessed_by}`}.</p>
      <div className="mt-4 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        {inspection.result === 'FAILED' && <Button variant="outline" className="text-danger" onClick={() => onNcr(inspection)}>Raise NCR</Button>}
        <Button variant="outline" onClick={() => onPhotos(inspection)}><Image /> Photos</Button>
        <Button variant="outline" asChild><a href={`/api/qc/inspections/${inspection.id}/document.pdf`} target="_blank" rel="noopener"><FileText /> PDF</a></Button>
        {open && <Button variant="outline" loading={save.isPending} onClick={() => save.mutate(false)}>Save</Button>}
        {open && can('site.signoff') && <Button loading={save.isPending} onClick={() => save.mutate(true)}>Close it</Button>}
        {!open && <Button onClick={onClose}>Done</Button>}
      </div>
    </div>
  )
}
