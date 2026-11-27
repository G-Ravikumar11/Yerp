import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Upload } from 'lucide-react'
import { Badge, Button, Modal } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { plural } from '@/lib/format'
import { budgetFileUrl, budgetKey, commitBudgetUpload, previewBudgetUpload, type BudgetUploadPlan, type BudgetUploadRow } from '@/api/budgeting'

function Rows({ title, tone, rows }: { title: string; tone: 'success' | 'danger' | 'warning'; rows: BudgetUploadRow[] }) {
  if (!rows.length) return null
  return (
    <section className="space-y-1.5">
      <h3 className="flex items-center gap-2 text-sm font-semibold">{title} <Badge tone={tone}>{rows.length}</Badge></h3>
      <ul className="max-h-56 divide-y divide-border overflow-auto rounded-md border border-border text-sm">
        {rows.map((r) => (
          <li key={r.row} className="px-3 py-1.5">
            <span className="font-medium">Row {r.row}: {r.item || '(no description)'}</span>
            <span className="block text-xs text-muted-foreground">{r.message}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * The budget filled in Excel, uploaded by the Master. The sheet is checked first and the result shown line by line; only the
 * lines not yet budgeted are added, on the button. Lines already budgeted in the app are never changed or entered twice.
 */
export function BudgetUploadModal({ job, onClose }: { job: number; onClose: () => void }) {
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [plan, setPlan] = useState<BudgetUploadPlan | null>(null)
  const [problem, setProblem] = useState('')
  const check = useAction((f: File) => previewBudgetUpload(job, f), {
    success: false,
    onSuccess: (p) => setPlan(p),
    onError: (e) => { setPlan(null); setProblem(e instanceof ApiError ? e.detail : 'That file could not be checked.') },
  })
  const save = useAction(() => commitBudgetUpload(job, file as File), {
    success: (r) => `${plural(r.added, 'line')} added to the budget.`,
    onSuccess: (r) => { qc.setQueryData(budgetKey(job), r.budget); qc.invalidateQueries({ queryKey: budgetKey(job) }); onClose() },
  })
  const pick = (f: File | null) => {
    setFile(f); setPlan(null); setProblem('')
    if (f) check.mutate(f)
  }
  const of = (s: BudgetUploadRow['status']) => (plan?.rows ?? []).filter((r) => r.status === s)
  const differing = of('kept').filter((r) => r.message.includes('other figures'))
  const adding = plan?.counts.add ?? 0

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Upload the filled budget" size="lg"
      description="For a budget filled in Excel. Only lines not yet budgeted are added. Lines already budgeted here are left exactly as they are."
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!plan || adding === 0 || check.isPending}>
          <Upload /> {adding ? `Add ${plural(adding, 'line')} to the budget` : 'Nothing to add'}
        </Button>
      </>}>
      <div className="space-y-4 text-sm">
        <ol className="list-decimal space-y-1 pl-5">
          <li><a className="font-medium text-primary hover:underline" href={budgetFileUrl(job)}>Download the budget Excel</a> (the same as the Excel button).</li>
          <li>Fill <b>Material per unit</b>, <b>Labour per unit</b> and <b>Plant &amp; other per unit</b> for the lines marked <b>No</b> under Budgeted. Do not change the Item or Description.</li>
          <li>Choose the file below. It is checked first; nothing is saved until you press Add.</li>
        </ol>
        <input type="file" accept=".xlsx" aria-label="The filled budget sheet" onChange={(e) => pick(e.target.files?.[0] ?? null)} />
        {check.isPending && <p className="text-muted-foreground">Checking the sheet...</p>}
        {problem && <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-danger">{problem}</p>}
        {plan && (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="What the sheet will do">
              <div className="rounded-lg border border-success/40 bg-success-soft px-3 py-2"><p className="text-xl font-semibold text-success">{plan.counts.add}</p><p className="text-xs">Will be added</p></div>
              <div className="rounded-lg border border-border px-3 py-2"><p className="text-xl font-semibold">{plan.counts.kept}</p><p className="text-xs">Already budgeted - not touched</p></div>
              <div className="rounded-lg border border-border px-3 py-2"><p className="text-xl font-semibold">{plan.counts.empty}</p><p className="text-xs">Left empty - for later</p></div>
              <div className={`rounded-lg border px-3 py-2 ${plan.counts.error ? 'border-danger/40 bg-danger-soft' : 'border-border'}`}><p className={`text-xl font-semibold ${plan.counts.error ? 'text-danger' : ''}`}>{plan.counts.error}</p><p className="text-xs">Problems - skipped</p></div>
            </div>
            <Rows title="Problems - these rows are skipped. Fix them in Excel and upload again." tone="danger" rows={of('error')} />
            <Rows title="Will be added" tone="success" rows={of('add')} />
            <Rows title="Already budgeted here, but the sheet has other figures - not changed" tone="warning" rows={differing} />
            {adding === 0 && !plan.counts.error && <p className="text-muted-foreground">Nothing new to add: every line in the sheet with a cost is already budgeted.</p>}
          </>
        )}
      </div>
    </Modal>
  )
}
