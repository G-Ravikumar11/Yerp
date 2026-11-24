import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CircleCheck, ListChecks, TriangleAlert } from 'lucide-react'
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui'
import { get } from '@/lib/api'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'

/** The budget item's own figures: the whole BOQ of every live project, and what is left on each (services/setup_check.py). */
interface BudgetBreakdown {
  totals: { lines: number; budgeted: number; partial: number; unbudgeted: number; approved_value: number; budgeted_value: number; remaining_value: number; completion_percent: number; value_percent: number }
  projects: { job_id: number; code: string; name: string; lines: { key: string; item_no: string; description: string; unit: string; status: string; quantity: number; value: number }[] }[]
}

interface SetupItem {
  key: string
  title: string
  detail: string
  count: number
  link: string
  fix: string
  ok: boolean
  budget?: BudgetBreakdown
}

export const useSetupCheck = (enabled: boolean) =>
  useQuery({ queryKey: ['setup-check'], enabled, staleTime: 60_000, queryFn: () => get<{ items: SetupItem[]; to_do: number; total: number }>('/api/setup-check') })

/**
 * What the business's controls rely on that is not yet set - approval routes, budgets, the company's own details - each
 * with the screen that puts it right. Left blank, a control falls back to the Master; this keeps that in sight. Shown to
 * the Master on the Command Center while anything is left, and gone once everything is set.
 */
export function SetupCheck() {
  const { isOwner } = useSession()
  const q = useSetupCheck(isOwner)
  const [showAll, setShowAll] = useState(false)
  if (!isOwner || !q.data || q.data.to_do === 0) return null
  const items = showAll ? q.data.items : q.data.items.filter((i) => !i.ok)
  return (
    <Card className="mb-5 border-warning/40" aria-labelledby="setup-check-title">
      <CardHeader className="pb-2">
        <CardTitle id="setup-check-title" className="flex items-center gap-2 text-base">
          <ListChecks className="size-5 text-warning" aria-hidden /> Setup check - {q.data.to_do} of {q.data.total} still to do
        </CardTitle>
        <CardDescription>Until these are set, the checks that rely on them fall back to you.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map((i) => (
          <div key={i.key} className="flex flex-wrap items-center gap-3 rounded-lg border border-border px-3 py-2.5">
            {i.ok ? <CircleCheck className="size-4 shrink-0 text-success" aria-label="Done" /> : <TriangleAlert className="size-4 shrink-0 text-warning" aria-label="To do" />}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{i.title}</p>
              <p className="text-[13px] text-muted-foreground">{i.detail}</p>
              {i.budget && <BudgetDetail b={i.budget} />}
            </div>
            {!i.ok && (
              <Button size="sm" asChild>
                <Link to={i.link}>{i.fix}</Link>
              </Button>
            )}
          </div>
        ))}
        <button type="button" onClick={() => setShowAll((v) => !v)} className="text-[13px] font-medium text-primary hover:underline">
          {showAll ? 'Show only what is left' : 'Show what is already done too'}
        </button>
      </CardContent>
    </Card>
  )
}

/** The BOQ budget in figures, and each project with lines still to budget, linked to its HO QS control view. */
function BudgetDetail({ b }: { b: BudgetBreakdown }) {
  const t = b.totals
  return (
    <div className="mt-1.5 text-[13px]">
      <p className="text-muted-foreground">
        {t.lines} lines: {t.budgeted} budgeted, {t.partial} partly, {t.unbudgeted} not at all ({t.completion_percent}%). Value {formatINR(t.budgeted_value)} of {formatINR(t.approved_value)} budgeted, {formatINR(t.remaining_value)} to go.
      </p>
      {b.projects.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {b.projects.slice(0, 6).map((p) => (
            <li key={p.job_id}>
              <Link className="font-medium text-primary hover:underline" to={`/projects/budgeting?job=${p.job_id}`}>{[p.code, p.name].filter(Boolean).join(' ')}</Link>
              <span className="text-muted-foreground"> - {p.lines.length} line{p.lines.length === 1 ? '' : 's'} to budget: {p.lines.slice(0, 3).map((l) => `${l.item_no ? l.item_no + ' ' : ''}${l.description.split('\n')[0].slice(0, 40)}`).join('; ')}{p.lines.length > 3 ? '; ...' : ''}</span>
            </li>
          ))}
          {b.projects.length > 6 && <li className="text-muted-foreground">and {b.projects.length - 6} more projects</li>}
        </ul>
      )}
    </div>
  )
}
