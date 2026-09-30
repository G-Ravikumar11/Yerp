import { useRef, useState } from 'react'
import { Button, Field, Modal, Select } from '@/components/ui'
import { clientOrderKeys, uploadOrderSheet, useJobOptions, validateOrderSheet, type SheetResult } from '@/api/clientOrders'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'

/** Bring in an order that already exists as a sheet. Checked first: nothing is saved while anything is wrong. */
export function OrderSheetModal({ open, onOpenChange, staff }: { open: boolean; onOpenChange: (o: boolean) => void; staff: boolean }) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Client work order from a file" description="One line per item sold. Line numbers below match what Excel shows.">
      {open && <SheetForm staff={staff} onClose={() => onOpenChange(false)} />}
    </Modal>
  )
}

function SheetForm({ staff, onClose }: { staff: boolean; onClose: () => void }) {
  const jobs = useJobOptions(staff)
  const file = useRef<HTMLInputElement>(null)
  const [job, setJob] = useState('')
  const [picked, setPicked] = useState<File | null>(null)
  const [result, setResult] = useState<SheetResult | null>(null)

  const check = useAction(() => validateOrderSheet(picked!), {
    success: (r) => (r.ok ? `Validated - ${formatINR(r.total_value ?? 0)}` : `${r.errors?.length ?? 0} error(s)`),
    onSuccess: (r) => setResult(r),
  })
  const create = useAction(() => uploadOrderSheet(picked!, Number(job)), {
    invalidate: [clientOrderKeys.all],
    success: (r) => r.message ?? '',
    onSuccess: (r) => {
      setResult(r)
      if (r.work_order) onClose()
    },
  })

  return (
    <div>
      <div className="grid gap-4">
        <Field label="Job" htmlFor="sh-job">
          <Select id="sh-job" value={job} onChange={(e) => setJob(e.target.value)} placeholder={jobs.isPending ? 'Loading...' : 'Choose the job'} options={(jobs.data ?? []).map((j) => ({ value: j.id, label: `${j.number} - ${j.name}` }))} />
        </Field>
        <Field label="Sheet" htmlFor="sh-file" hint="An .xlsx or .csv laid out like the template.">
          <input
            ref={file}
            id="sh-file"
            type="file"
            accept=".xlsx,.xlsm,.csv"
            onChange={(e) => {
              setPicked(e.target.files?.[0] ?? null)
              setResult(null)
            }}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-2 file:text-sm file:font-medium hover:file:bg-accent"
          />
        </Field>
      </div>

      {result && (
        <div className="mt-4 space-y-3 text-sm">
          {!!result.errors?.length && (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger-soft p-3">
              <p className="font-medium text-danger">{result.errors.length} error(s) - nothing was saved</p>
              <ul className="mt-1.5 list-disc pl-5 text-[13px] text-muted-foreground">
                {result.errors.map((e, i) => (
                  <li key={i}>
                    Line {e.line} · {e.field} · {e.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!!result.warnings?.length && (
            <div className="rounded-lg border border-warning/40 bg-warning-soft p-3">
              <p className="font-medium text-warning">{result.warnings.length} reused</p>
              <ul className="mt-1.5 list-disc pl-5 text-[13px] text-muted-foreground">
                {result.warnings.map((w, i) => (
                  <li key={i}>
                    Line {w.line} · {w.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {result.ok && !result.errors?.length && (
            <p className="rounded-lg border border-success/40 bg-success-soft p-3 font-medium text-success">
              Validated - {result.lines?.length ?? 0} line(s), order value {formatINR(result.total_value ?? 0)}.
            </p>
          )}
        </div>
      )}

      <div className="mt-5 flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="outline" loading={check.isPending} disabled={!picked} onClick={() => check.mutate()}>
          Check the sheet
        </Button>
        <Button loading={create.isPending} disabled={!picked || !job} onClick={() => create.mutate()}>
          Create the order
        </Button>
      </div>
    </div>
  )
}
