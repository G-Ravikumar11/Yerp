import { useState } from 'react'
import { Target } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { PromptModal } from '@/components/data/PromptModal'
import { Badge, Button, Skeleton } from '@/components/ui'
import { staffKeys, updateGoal, useGoals, type Goal } from '@/api/staff'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'

const pct = (g: Goal) => (g.target_value > 0 ? Math.min(Math.round((g.current_value / g.target_value) * 100), 100) : 0)
const tone = (p: string) => (p === 'high' ? 'danger' : p === 'low' ? 'success' : 'warning') as 'danger' | 'success' | 'warning'

/** What the person has been asked to achieve, and how far along they are. */
export default function GoalsPage() {
  const q = useGoals()
  const [editing, setEditing] = useState<Goal | null>(null)
  const save = useAction((v: { g: Goal; value: number }) => updateGoal(v.g.id, v.value), { invalidate: [staffKeys.all], success: 'Progress updated', onSuccess: () => setEditing(null) })
  return (
    <>
      <PageHeader eyebrow="My work" title="My Goals" description="What you have been set, and how far along you are. Update your progress as you go." />
      {q.isPending ? <Skeleton className="h-40 w-full" /> : q.data?.length ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {q.data.map((g) => (
            <section key={g.id} aria-label={g.title} className="rounded-xl border border-border bg-card p-5 shadow-card">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0"><h2 className="font-semibold">{g.title}</h2>{g.description && <p className="mt-0.5 text-[13px] text-muted-foreground">{g.description}</p>}</div>
                <div className="flex shrink-0 gap-1.5"><Badge tone={tone(g.priority)}>{g.priority}</Badge><Badge tone={g.status === 'completed' ? 'success' : 'info'} dot>{g.status.replace('_', ' ')}</Badge></div>
              </div>
              <div className="mt-4">
                <div className="mb-1 flex justify-between text-[13px]"><span className="tabular">{g.current_value} of {g.target_value} {g.unit}</span><span className="tabular font-semibold">{pct(g)}%</span></div>
                <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct(g)} aria-valuemin={0} aria-valuemax={100}><div className={`h-full rounded-full ${g.status === 'completed' ? 'bg-success' : 'bg-primary'}`} style={{ width: `${pct(g)}%` }} /></div>
              </div>
              <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                <span>{g.category}{g.due_date && ` - due ${formatDate(g.due_date)}`}{g.created_by && ` - set by ${g.created_by}`}</span>
                {g.status !== 'completed' && <Button size="sm" variant="outline" onClick={() => setEditing(g)}>Update progress</Button>}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="grid place-items-center gap-2 rounded-xl border border-border bg-card py-16 text-center shadow-card"><Target className="size-10 text-muted-foreground" /><p className="font-medium">No goals yet</p><p className="text-sm text-muted-foreground">Goals your manager or HR sets for you appear here.</p></div>
      )}
      <PromptModal open={!!editing} title={editing ? `Update ${editing.title}` : ''} description="Where you are now." fields={[{ key: 'v', label: editing ? `Progress so far (target ${editing.target_value} ${editing.unit})` : '', initial: editing ? String(editing.current_value) : '', required: true }]} confirm="Save progress" busy={save.isPending} error={save.error?.message} onSubmit={(x) => editing && save.mutate({ g: editing, value: parseFloat(x.v) || 0 })} onClose={() => setEditing(null)} />
    </>
  )
}
