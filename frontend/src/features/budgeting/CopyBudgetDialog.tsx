import { useState } from 'react'
import { ConfirmDialog, Field, Select } from '@/components/ui'
import { budgetKey, type Budget } from '@/api/budgeting'
import { projectLabel, useProjects } from '@/api/projects'
import { post } from '@/lib/api'
import { useAction } from '@/lib/mutate'

/**
 * Budget a new BOQ in one go from a project already budgeted: each line takes the costs of the matching line there (the
 * same item code, else the same description and unit). Lines already budgeted here stay as they are unless overwritten.
 */
export function CopyBudgetDialog({ job, open, onClose }: { job: number; open: boolean; onClose: () => void }) {
  const projects = useProjects()
  const [from, setFrom] = useState(0)
  const [overwrite, setOverwrite] = useState(false)
  const copy = useAction(
    () => post<Budget & { message: string }>(`/api/jobs/${job}/budget/copy`, { from_job_id: from, overwrite }),
    { invalidate: [budgetKey(job), ['setup-check']], success: (r) => r.message, onSuccess: () => { setFrom(0); setOverwrite(false); onClose() } },
  )
  const others = (projects.data ?? []).filter((p) => p.id !== job)
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Copy the budget from another project"
      description="Each BOQ line here takes the costs of the matching line there - the same item code, or else the same description and unit. Check the copied figures before work orders go out at them."
      confirmLabel="Copy the budget"
      loading={copy.isPending}
      onConfirm={() => { if (from) copy.mutate() }}
    >
      <Field label="Copy from" htmlFor="copy-from">
        <Select id="copy-from" value={from || ''} onChange={(e) => setFrom(Number(e.target.value) || 0)} placeholder="Choose a project"
          options={others.map((p) => ({ value: p.id, label: projectLabel(p) }))} />
      </Field>
      <label className="mt-3 flex items-start gap-2 text-[13px]">
        <input type="checkbox" className="mt-0.5 size-4" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
        <span>Also replace lines that are already budgeted here (otherwise only the empty ones are filled)</span>
      </label>
    </ConfirmDialog>
  )
}
