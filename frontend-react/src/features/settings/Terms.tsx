import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Badge, Button, Input, Skeleton, Textarea } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { saveTerms, settingsKeys, useTerms, type TermClause } from '@/api/settings'
import { Section } from './Section'

/** The general conditions printed on every work order that has none of its own. */
export function Terms() {
  const q = useTerms()
  const [rows, setRows] = useState<TermClause[]>([])
  useEffect(() => { if (q.data) setRows(q.data.library.map((t) => ({ ...t }))) }, [q.data])
  const save = useAction((list: TermClause[]) => saveTerms(list), { invalidate: [settingsKeys.all, ['orders']] })
  const edit = (i: number, patch: Partial<TermClause>) => setRows((l) => l.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  return (
    <Section
      title="Work order conditions"
      description="Printed on every work order that has none of its own. Edit them once here."
      actions={q.data && <Badge tone={q.data.custom ? 'success' : 'neutral'}>{q.data.custom ? 'Your own' : 'Standard'}</Badge>}
    >
      {q.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <>
          <div className="flex flex-col gap-3">
            {rows.map((r, i) => (
              <div key={i} className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-[12rem_1fr_auto]">
                <Input aria-label={`Condition ${i + 1} heading`} placeholder="Heading" value={r.clause_category} onChange={(e) => edit(i, { clause_category: e.target.value })} />
                <Textarea aria-label={`Condition ${i + 1} text`} rows={2} value={r.clause_text} onChange={(e) => edit(i, { clause_text: e.target.value })} />
                <Button type="button" variant="ghost" size="icon" aria-label={`Remove condition ${i + 1}`} onClick={() => setRows((l) => l.filter((_, j) => j !== i))}><Trash2 className="size-4" /></Button>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setRows((l) => [...l, { clause_category: '', clause_text: '' }])}><Plus /> Add a condition</Button>
            <Button type="button" loading={save.isPending} onClick={() => save.mutate(rows)}>Save conditions</Button>
            {q.data?.custom && <Button type="button" variant="ghost" onClick={() => save.mutate([])}>Go back to the standard conditions</Button>}
          </div>
        </>
      )}
    </Section>
  )
}
